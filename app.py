import streamlit as st
import pandas as pd
import numpy as np

# --- 网页基础设置 ---
st.set_page_config(page_title="VC POS 波动预警终极版", layout="wide")
st.title("🚨 Amazon VC POS 每日波动预警系统 (SOP 终极还原版)")
st.markdown("严格按照 Skill 需求文档构建，包含多维清洗、真实 L30D 均销计算、父子双维度下钻及 4 层预警全数据明细。")

# --- 4层预警核心算法 (严格还原 PRD) ---
def calculate_alert_details(sales_latest, sales_prev, l30d_avg):
    avg_sales = (sales_latest + sales_prev) / 2
    sales_change = sales_latest - sales_prev
    
    alert_tier = '无预警'
    alert_reason = ''
    impact_level = 'NORMAL'
    driving_factor = '正常波动'
    
    # 🔴 第一层 (高销突变)
    if avg_sales >= 10 and abs(sales_change) >= 15:
        alert_tier = '🔴 第一层 (高销突变)'
        if sales_change <= -30:
            impact_level = 'CRITICAL'
            alert_reason = '高销爆跌 (降幅 >= 30)'
            driving_factor = '核心流量断流或断货风险'
        elif sales_change < 0:
            impact_level = 'HIGH'
            alert_reason = '高销明显下滑'
            driving_factor = '市场需求波动或竞品冲击'
        else:
            impact_level = 'HIGH'
            alert_reason = '高销异常飙升'
            driving_factor = '大促活动或爆单，速查库存'
            
    # ⚠️ 第二层 (中销波动)
    elif 3 <= avg_sales < 10 and sales_prev > 0 and (abs(sales_change) / sales_prev) >= 0.60:
        alert_tier = '⚠️ 第二层 (中销波动)'
        impact_level = 'MEDIUM'
        if sales_change < 0:
            alert_reason = f'中销剧烈下滑 (跌幅 {int((abs(sales_change)/sales_prev)*100)}%)'
            driving_factor = '潜在 Listing 差评或购物车丢失'
        else:
            alert_reason = f'中销剧烈飙升 (涨幅 {int((sales_change/sales_prev)*100)}%)'
            driving_factor = '关键词排名破圈或跟价促销'
            
    # ⚪ 第三层 (归零预警)
    elif l30d_avg >= 3 and sales_prev >= 3 and sales_latest == 0:
        alert_tier = '⚪ 第三层 (归零预警)'
        impact_level = 'HIGH'
        alert_reason = f'历史稳定畅销单品突然断崖式归零 (L30D均销: {l30d_avg:.1f})'
        driving_factor = '极大概率触发审核、被抢Buybox或系统Bug封杀'
        
    # ℹ️ 第四层 (恢复预警)
    elif sales_prev == 0 and sales_latest >= 3:
        alert_tier = 'ℹ️ 第四层 (恢复预警)'
        impact_level = 'LOW'
        alert_reason = '从零起死回生'
        driving_factor = '海外仓刚入库上架或跟价恢复'
        
    return alert_tier, alert_reason, impact_level, driving_factor

# --- 网页上传组件 ---
uploaded_file = st.file_uploader("📂 请上传原始 VC ASIN 报表 (支持 xlsx 或 csv)", type=['xlsx', 'csv'])

if uploaded_file is not None:
    with st.spinner('🔥 正在执行深度漏斗清洗、横向计算30天均销、合并父ASIN汇总...'):
        try:
            # 1. 读取原始大表 (无 header 结构，彻底保留原始行列)
            if uploaded_file.name.endswith('.csv'):
                raw_df = pd.read_csv(uploaded_file, header=None, low_memory=False)
            else:
                raw_df = pd.read_excel(uploaded_file, header=None)
            
            # 向下填充 Parent ASIN (第0列)
            raw_df.iloc[:, 0] = raw_df.iloc[:, 0].ffill()
            
            # 2. 纵向定位并过滤表头文字
            # 找到真正的 ASIN 数据从哪一行开始 (查找包含 'B0' 类似结构的行，或避开前两行)
            data_start_row = 2
            
            # 3. 横向扫描识别所有日期和对应的 Ordered Units 列索引
            date_row = raw_df.iloc[0, :]
            sub_header_row = raw_df.iloc[1, :]
            
            date_dict = {} # 格式: {日期: 列索引}
            all_ordered_units_indices = [] # 用于计算L30D
            
            for col_idx in range(20, raw_df.shape[1]):
                # 检查当前列或其左侧最近的合并日期
                potential_date_val = str(date_row.iloc[col_idx]).strip()
                sub_header_val = str(sub_header_row.iloc[col_idx]).strip().lower()
                
                # 如果当前列有明确日期，记录它
                try:
                    p_date = pd.to_datetime(potential_date_val)
                    if not pd.isna(p_date):
                        current_date = p_date.date()
                except:
                    pass
                
                # 如果当前子列是我们需要计算的销量的列
                if 'ordered units' in sub_header_val or sub_header_val == '0' or pd.isna(sub_header_row.iloc[col_idx]):
                    # 如果原表表头不标准，默认每个日期块的第一列(Offset+0)就是 Ordered Units
                    # 验证当前列对应的日期是否存在
                    all_ordered_units_indices.append(col_idx)
                    if 'current_date' in locals() and current_date not in date_dict:
                        date_dict[current_date] = col_idx
            
            # 排序日期
            sorted_dates = sorted(list(date_dict.keys()), reverse=True)
            
            if len(sorted_dates) < 2:
                st.error("❌ 无法从数据表中提取出至少两天的有效历史日期，请检查报表格式！")
                st.stop()
                
            latest_date = sorted_dates[0]
            prev_date = sorted_dates[1]
            
            latest_col_idx = date_dict[latest_date]
            prev_col_idx = date_dict[prev_date]
            
            # --- 4. 核心遍历与数据清洗 (子ASIN级) ---
            child_records = []
            
            for idx, row in raw_df.iloc[data_start_row:].iterrows():
                parent_asin = str(row.iloc[0]).strip()
                asin = str(row.iloc[1]).strip()
                brand = str(row.iloc[2]).strip()
                division = str(row.iloc[3]).strip()
                om = str(row.iloc[11]).strip()
                retail_status = str(row.iloc[18]).strip().lower()
                title = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else ''
                
                # 严格剔除过滤规则
                if retail_status in ['discontinued', 'temp discontinued']: continue
                if division in ['FUR', 'LGT', 'ART', 'APL', 'PET', 'PETB']: continue
                if om.lower() == 'discontinued': continue
                if asin == 'nan' or asin == 'ASIN': continue
                
                # 精准提取最近两天销量
                try:
                    s_latest = float(row.iloc[latest_col_idx]) if pd.notna(row.iloc[latest_col_idx]) else 0.0
                    s_prev = float(row.iloc[prev_col_idx]) if pd.notna(row.iloc[prev_col_idx]) else 0.0
                except:
                    s_latest, s_prev = 0.0, 0.0
                
                # 【大升级】计算该 ASIN 真正的过去 30 天日均销量
                historical_sales = []
                for c_idx in all_ordered_units_indices:
                    try:
                        val = row.iloc[c_idx]
                        historical_sales.append(float(val) if pd.notna(val) else 0.0)
                    except:
                        pass
                l30d_avg = np.mean(historical_sales) if historical_sales else 0.0
                
                # 触发预警判定
                tier, reason, impact, driving = calculate_alert_details(s_latest, s_prev, l30d_avg)
                
                child_records.append({
                    'OM': om,
                    'Brand': brand,
                    'Parent ASIN': parent_asin,
                    'ASIN': asin,
                    'Product Title': title[:40] + '...' if len(title) > 40 else title,
                    f'前日销量 ({prev_date})': int(s_prev),
                    f'昨日销量 ({latest_date})': int(s_latest),
                    '销量每日净波动': int(s_latest - s_prev),
                    '真实 L30D 均销': round(l30d_avg, 2),
                    '影响级别 (Impact)': impact,
                    '预警层级 (Tier)': tier,
                    '预警原因明细': reason,
                    '驱动因素预测': driving
                })
                
            child_df = pd.DataFrame(child_records)
            
            if child_df.empty:
                st.info("🎉 经过漏斗清洗后，今日无任何 ASIN 触发异常波动。")
                st.stop()
                
            # 过滤出有预警的单品
            alert_child_df = child_df[child_df['预警层级 (Tier)'] != '无预警'].copy()
            alert_child_df['绝对波动'] = alert_child_df['销量每日净波动'].abs()
            alert_child_df = alert_child_df.sort_values(by='绝对波动', ascending=False).drop(columns=['绝对波动'])
            
            # --- 5. 聚合计算：父 ASIN 维度汇总 (100% 还原 PRD 要求的维度) ---
            parent_group = child_df.groupby('Parent ASIN').agg({
                'ASIN': 'count',
                f'前日销量 ({prev_date})': 'sum',
                f'昨日销量 ({latest_date})': 'sum',
                '真实 L30D 均销': 'sum',
                'OM': 'first',
                'Brand': 'first'
            }).reset_index()
            
            parent_records = []
            for idx, row in parent_group.iterrows():
                p_asin = row['Parent ASIN']
                asin_count = row['ASIN']
                p_prev = row[f'前日销量 ({prev_date})']
                p_latest = row[f'昨日销量 ({latest_date})']
                p_l30d = row['真实 L30D 均销']
                
                p_tier, p_reason, p_impact, p_driving = calculate_alert_details(p_latest, p_prev, p_l30d)
                
                if p_tier != '无预警':
                    parent_records.append({
                        'OM': row['OM'],
                        'Brand': row['Brand'],
                        'Parent ASIN': p_asin,
                        '下属子 ASIN 数量': asin_count,
                        f'父体前日总销量': int(p_prev),
                        f'父体昨日总销量': int(p_latest),
                        '父体每日净波动': int(p_latest - p_prev),
                        '父体 L30D 总均销': round(p_l30d, 2),
                        '影响级别 (Impact)': p_impact,
                        '预警层级 (Tier)': p_tier,
                        '预警原因明细': p_reason,
                        '驱动因素预测': p_driving
                    })
            parent_df = pd.DataFrame(parent_records)
            if not parent_df.empty:
                parent_df['绝对波动'] = parent_df['父体每日净波动'].abs()
                parent_df = parent_df.sort_values(by='绝对波动', ascending=False).drop(columns=['绝对波动'])
            
            # --- 6. 网页端高能 UI 渲染 ---
            st.success(f"✅ 深度数据拆解完成！对比周期: **{prev_date}** 🆚 **{latest_date}**")
            
            # 数据统计总览卡片
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("高危红标 (🔴 第一层)", len(alert_child_df[alert_child_df['预警层级 (Tier)'].str.contains('🔴')]))
            col2.metric("中危黄标 (⚠️ 第二层)", len(alert_child_df[alert_child_df['预警层级 (Tier)'].str.contains('⚠️')]))
            col3.metric("归零风险 (⚪ 第三层)", len(alert_child_df[alert_child_df['预警层级 (Tier)'].str.contains('⚪')]))
            col4.metric("触发预警父体数", len(parent_df))
            
            # 标签页划分 (子维度 vs 父维度)
            tab1, tab2 = st.tabs(["🛒 子 ASIN 风险明细排行", "📦 父 ASIN 汇总分析看板"])
            
            # 高亮函数
            def style_picker(val):
                if isinstance(val, str):
                    if '🔴' in val or 'CRITICAL' in val: return 'background-color: #FFC7CE; color: #9C0006; font-weight: bold'
                    if '⚠️' in val or 'HIGH' in val: return 'background-color: #FFEB9C; color: #9C6500'
                    if '⚪' in val or 'MEDIUM' in val: return 'background-color: #F2F2F2; color: #333333'
                    if 'ℹ️' in val or 'LOW' in val: return 'background-color: #DDEBF7; color: #004E82'
                return ''
            
            with tab1:
                st.write(f"共有 **{len(alert_child_df)}** 个子 ASIN 触发异动。支持点击表头进行二次排序筛选：")
                st.dataframe(
                    alert_child_df.style.map(style_picker, subset=['预警层级 (Tier)', '影响级别 (Impact)']),
                    use_container_width=True, height=500
                )
                
            with tab2:
                if not parent_df.empty:
                    st.write(f"共有 **{len(parent_df)}** 个合并父体触发团队级控速线：")
                    st.dataframe(
                        parent_df.style.map(style_picker, subset=['预警层级 (Tier)', '影响级别 (Impact)']),
                        use_container_width=True, height=500
                    )
                else:
                    st.info("🟢 父 ASIN 聚合层级未发现剧烈突变。")
                    
        except Exception as e:
            st.error(f"💥 深度分析失败。可能是原表格字段被大幅篡改。具体研发错误信息：{e}")
