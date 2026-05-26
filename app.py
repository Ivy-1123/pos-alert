import streamlit as st
import pandas as pd
import numpy as np

# --- 网页基础设置 ---
st.set_page_config(page_title="VC POS 7大指标深度预警系统", layout="wide")
st.title("🚨 Amazon VC Daily POS 核心指标全域预警看板")
st.markdown("还原 3 大核心架构看板，全维监控：销量、GV、价格、SPSD广告、SBDSP广告、CVR、TACOS。")

# --- 辅助计算：根据表头名和偏移安全提取数据 ---
def get_row_val(row, base_idx, offset, fill_zero=True):
    try:
        val = row.iloc[base_idx + offset]
        if pd.isna(val) or str(val).strip() == '' or str(val).strip().lower() == 'nan':
            return 0.0 if fill_zero else np.nan
        # 移除百分号或逗号等干扰
        val_str = str(val).replace('%', '').replace(',', '').strip()
        return float(val_str)
    except:
        return 0.0 if fill_zero else np.nan

if 'clicked' not in st.session_state:
    st.session_state.clicked = False

# --- 网页上传组件 ---
uploaded_file = st.file_uploader("📂 请上传原始 VC ASIN 复合数据表 (支持 xlsx 或 csv)", type=['xlsx', 'csv'])

if uploaded_file is not None:
    with st.spinner('🔥 正在构建多维数据立方体，横向对齐 7 大核心财务与运营指标...'):
        try:
            # 1. 读取原始大表 (无 header 结构，防合并单元格错位)
            if uploaded_file.name.endswith('.csv'):
                raw_df = pd.read_csv(uploaded_file, header=None, low_memory=False)
            else:
                raw_df = pd.read_excel(uploaded_file, header=None)
            
            # 向下填充 Parent ASIN (第0列)
            raw_df.iloc[:, 0] = raw_df.iloc[:, 0].ffill()
            
            # 2. 横向多行表头深度探测
            date_row = raw_df.iloc[0, :]
            sub_header_row = raw_df.iloc[1, :]
            
            # 探测所有日期块的起始列位置
            date_blocks = {} # {日期: 该日期块对应的各个指标相对列偏}
            unique_ordered_dates = []
            
            # 精准解析出每个日期块下面各子指标的绝对列索引
            current_date = None
            for col_idx in range(20, raw_df.shape[1]):
                date_val = str(date_row.iloc[col_idx]).strip()
                sub_val = str(sub_header_row.iloc[col_idx]).strip().lower()
                
                try:
                    p_date = pd.to_datetime(date_val)
                    if not pd.isna(p_date):
                        current_date = p_date.date()
                        if current_date not in date_blocks:
                            date_blocks[current_date] = {}
                            unique_ordered_dates.append(current_date)
                except:
                    pass
                
                if current_date is not None:
                    # 通过子表头字符模糊匹配你的 7 大指标索引位置
                    if 'ordered units' in sub_val or sub_val == '0': date_blocks[current_date]['units'] = col_idx
                    elif 'views' in sub_val or 'gv' in sub_val: date_blocks[current_date]['gv'] = col_idx
                    elif 'asp' in sub_val or 'price' in sub_val or 'average retail price' in sub_val: date_blocks[current_date]['price'] = col_idx
                    elif 'spsd' in sub_val or 'sp spend' in sub_val: date_blocks[current_date]['sp'] = col_idx
                    elif 'sbdsp' in sub_val or 'sb spend' in sub_val: date_blocks[current_date]['sb'] = col_idx
                    elif 'cvr' in sub_val or 'conversion rate' in sub_val: date_blocks[current_date]['cvr'] = col_idx
                    elif 'tacos' in sub_val: date_blocks[current_date]['tacos'] = col_idx

            # 提取排序后的历史日期列表
            sorted_dates = sorted(unique_ordered_dates, reverse=True)
            if len(sorted_dates) < 2:
                st.error("❌ 无法从数据表中提取出至少两天的有效历史日期周期，请检查源表头。")
                st.stop()
                
            latest_d = sorted_dates[0]
            prev_d = sorted_dates[1]
            
            # 检查最近两天是否配齐了基础的销量列索引
            if 'units' not in date_blocks[latest_d] or 'units' not in date_blocks[prev_d]:
                st.error(f"❌ 未能完美识别出 {latest_d} 或 {prev_d} 的 Ordered Units 销量列，请确认第二行表头文案。")
                st.stop()
            
            # --- 3. 纵向漏斗清洗 & 核心底层指标抓取 (剔除汇总行) ---
            child_base_data = []
            
            for idx, row in raw_df.iloc[2:].iterrows():
                parent_asin = str(row.iloc[0]).strip()
                asin = str(row.iloc[1]).strip()
                brand = str(row.iloc[2]).strip()
                division = str(row.iloc[3]).strip()
                title = str(row.iloc[5]).strip()
                om = str(row.iloc[11]).strip()
                retail_status = str(row.iloc[18]).strip().lower()
                
                # 🛑 核心过滤：彻底拦截掉“总计/Total”等系统统计行
                if parent_asin.lower() in ['total', '总计', 'nan', '']: continue
                if asin.lower() in ['total', '总计', 'nan', '', 'asin']: continue
                if retail_status in ['discontinued', 'temp discontinued']: continue
                if division in ['FUR', 'LGT', 'ART', 'APL', 'PET', 'PETB']: continue
                if om.lower() == 'discontinued': continue
                
                # --- 7 大核心指标动态安全抓取 ---
                b_l = date_blocks[latest_d]
                b_p = date_blocks[prev_d]
                
                # 1. 销量
                u_l = get_row_val(row, b_l['units'], 0)
                u_p = get_row_val(row, b_p['units'], 0)
                # 2. GV
                gv_l = get_row_val(row, b_l.get('gv', b_l['units']), 0)
                gv_p = get_row_val(row, b_p.get('gv', b_p['units']), 0)
                # 3. 价格
                pr_l = get_row_val(row, b_l.get('price', b_l['units']), 0)
                pr_p = get_row_val(row, b_p.get('price', b_p['units']), 0)
                # 4. SPSD Spend
                sp_l = get_row_val(row, b_l.get('sp', b_l['units']), 0)
                sp_p = get_row_val(row, b_p.get('sp', b_p['units']), 0)
                # 5. SBDSP Spend
                sb_l = get_row_val(row, b_l.get('sb', b_l['units']), 0)
                sb_p = get_row_val(row, b_p.get('sb', b_p['units']), 0)
                # 6. CVR
                cvr_l = get_row_val(row, b_l.get('cvr', b_l['units']), 0)
                cvr_p = get_row_val(row, b_p.get('cvr', b_p['units']), 0)
                # 7. TACOS
                tc_l = get_row_val(row, b_l.get('tacos', b_l['units']), 0)
                tc_p = get_row_val(row, b_p.get('tacos', b_p['units']), 0)
                
                child_base_data.append({
                    'Parent ASIN': parent_asin, 'ASIN': asin, 'Brand': brand, 'Division': division,
                    'Product Title': title[:30] + '...' if len(title) > 30 else title, 'OM': om, 'Retail Status': retail_status,
                    'units_l': u_l, 'units_p': u_p, 'gv_l': gv_l, 'gv_p': gv_p, 'price_l': pr_l, 'price_p': pr_p,
                    'sp_l': sp_l, 'sp_p': sp_p, 'sb_l': sb_l, 'sb_p': sb_p, 'cvr_l': cvr_l, 'cvr_p': cvr_p, 'tacos_l': tc_l, 'tacos_p': tc_p,
                    # 用于横向扫描全周期的销量存储
                    'row_all_cells': row
                })
                
            df_child_master = pd.DataFrame(child_base_data)
            if df_child_master.empty:
                st.warning("⚠️ 过滤清洗后未留下有效的产品明细数据，请确认表格过滤条件。")
                st.stop()
                
            # ==================== SHEET 1: 子ASIN - 全部波动 ====================
            s1_records = []
            for _, r in df_child_master.iterrows():
                u_diff = r['units_l'] - r['units_p']
                s1_records.append({
                    'OM': r['OM'], 'Brand': r['Brand'], 'Parent ASIN': r['Parent ASIN'], 'ASIN': r['ASIN'],
                    '产品品名': r['Product Title'], '状态': r['Retail Status'],
                    f'前日销量({prev_d})': int(r['units_p']), f'昨日销量({latest_d})': int(r['units_l']), '销量净波动': int(u_diff),
                    'GV前日': int(r['gv_p']), 'GV昨日': int(r['gv_l']), 'GV波动值': int(r['gv_l'] - r['gv_p']),
                    '单价前日': round(r['price_p'], 2), '单价昨日': round(r['price_l'], 2), '价格波动': round(r['price_l'] - r['price_p'], 2),
                    'SP广告前日': round(r['sp_p'], 1), 'SP广告昨日': round(r['sp_l'], 1), 'SPSD广告波动': round(r['sp_l'] - r['sp_p'], 1),
                    'SB广告前日': round(r['sb_p'], 1), 'SB广告昨日': round(r['sb_l'], 1), 'SBDSP广告波动': round(r['sb_l'] - r['sb_p'], 1),
                    '转化率前日(%)': round(r['cvr_p'], 2), '转化率昨日(%)': round(r['cvr_l'], 2), 'CVR净波动(%)': round(r['cvr_l'] - r['cvr_p'], 2),
                    'TACOS前日(%)': round(r['tacos_p'], 2), 'TACOS昨日(%)': round(r['tacos_l'], 2), 'TACOS波动(%)': round(r['tacos_l'] - r['tacos_p'], 2)
                })
            df_sheet1 = pd.DataFrame(s1_records)
            # 严格按照销量波动绝对值进行降序排列
            df_sheet1['abs_wave'] = df_sheet1['销量净波动'].abs()
            df_sheet1 = df_sheet1.sort_values(by='abs_wave', ascending=False).drop(columns=['abs_wave'])
            
            # ==================== SHEET 2: 父ASIN - 全部波动 ====================
            parent_group = df_child_master.groupby('Parent ASIN').agg({
                'ASIN': 'count', 'OM': 'first', 'Brand': 'first', 'Retail Status': 'first',
                'units_p': 'sum', 'units_l': 'sum', 'gv_p': 'sum', 'gv_l': 'sum',
                'price_p': 'mean', 'price_l': 'mean', 'sp_p': 'sum', 'sp_l': 'sum',
                'sb_p': 'sum', 'sb_l': 'sum', 'cvr_p': 'mean', 'cvr_l': 'mean',
                'tacos_p': 'mean', 'tacos_l': 'mean'
            }).reset_index()
            
            s2_records = []
            for _, r in parent_group.iterrows():
                p_u_diff = r['units_l'] - r['units_p']
                s2_records.append({
                    'OM': r['OM'], 'Brand': r['Brand'], 'Parent ASIN': r['Parent ASIN'], '下属子ASIN数': int(r['ASIN']),
                    '父体前日销量': int(r['units_p']), '父体昨日销量': int(r['units_l']), '父体销量净波动': int(p_u_diff),
                    '父体GV前日': int(r['gv_p']), '父体GV昨日': int(r['gv_l']), '父体GV波动': int(r['gv_l'] - r['gv_p']),
                    '平均单价前日': round(r['price_p'], 2), '平均单价昨日': round(r['price_l'], 2),
                    '父体SP费用前日': round(r['sp_p'], 1), '父体SP费用昨日': round(r['sp_l'], 1),
                    '父体SB费用前日': round(r['sb_p'], 1), '父体SB费用昨日': round(r['sb_l'], 1),
                    '父体均值CVR(%)': round(r['cvr_l'], 2), '父体均值TACOS(%)': round(r['tacos_l'], 2)
                })
            df_sheet2 = pd.DataFrame(s2_records)
            df_sheet2['abs_wave'] = df_sheet2['父体销量净波动'].abs()
            df_sheet2 = df_sheet2.sort_values(by='abs_wave', ascending=False).drop(columns=['abs_wave'])
            
            # ==================== SHEET 3: 父ASIN - weekly波动预警 ====================
            # 还原 Weekly 算法：比对过去7天总销量（最近7天 vs 上个7天）
            s3_records = []
            if len(sorted_dates) >= 14:
                last_7_days = sorted_dates[:7]
                prev_7_days = sorted_dates[7:14]
                
                for _, r in parent_group.iterrows():
                    p_asin = r['Parent ASIN']
                    # 获取该父体下所有子体的原始行数据累加历史
                    children_rows = df_child_master[df_child_master['Parent ASIN'] == p_asin]
                    
                    l7_units_sum, p7_units_sum = 0, 0
                    l7_gv_sum, p7_gv_sum = 0, 0
                    
                    for d in last_7_days:
                        if d in date_blocks:
                            for _, cr in children_rows.iterrows():
                                l7_units_sum += get_row_val(cr['row_all_cells'], date_blocks[d]['units'], 0)
                                l7_gv_sum += get_row_val(cr['row_all_cells'], date_blocks[d].get('gv', date_blocks[d]['units']), 0)
                    for d in prev_7_days:
                        if d in date_blocks:
                            for _, cr in children_rows.iterrows():
                                p7_units_sum += get_row_val(cr['row_all_cells'], date_blocks[d]['units'], 0)
                                p7_gv_sum += get_row_val(cr['row_all_cells'], date_blocks[d].get('gv', date_blocks[d]['units']), 0)
                    
                    weekly_diff = l7_units_sum - p7_units_sum
                    weekly_pct = (weekly_diff / p7_units_sum) if p7_units_sum > 0 else 0.0
                    
                    # 设定 Weekly 预警条件（如销量环比波动超 30% 触发）
                    w_alert = '正常'
                    if weekly_pct <= -0.30 and p7_units_sum > 20: w_alert = '🔴 周销量暴跌'
                    elif weekly_pct >= 0.30: w_alert = '🚀 周销量暴涨'
                    
                    s3_records.append({
                        'OM': r['OM'], 'Brand': r['Brand'], 'Parent ASIN': p_asin,
                        '本周7天总销量': int(l7_units_sum), '上周7天总销量': int(p7_units_sum),
                        '周销量净波动': int(weekly_diff), '周销量环比': f"{round(weekly_pct*100, 1)}%",
                        '本周总GV': int(l7_gv_sum), '周GV净波动': int(l7_gv_sum - p7_gv_sum),
                        '周度健康状态诊断': w_alert
                    })
            else:
                # 历史日期不足 14 天时的兜底显示
                for _, r in parent_group.iterrows():
                    s3_records.append({
                        'OM': r['OM'], 'Brand': r['Brand'], 'Parent ASIN': r['Parent ASIN'],
                        '提示信息': '当前上传的文件横向历史日期不足 14 天，无法完成周环比(Weekly)对比分析。'
                    })
            df_sheet3 = pd.DataFrame(s3_records)
            if '周销量净波动' in df_sheet3.columns:
                df_sheet3['abs_wave'] = df_sheet3['周销量净波动'].abs()
                df_sheet3 = df_sheet3.sort_values(by='abs_wave', ascending=False).drop(columns=['abs_wave'])

            # --- 4. 渲染多标签页完美 UI ---
            st.success(f"✅ 核心财务与广告数据对齐成功！对比周期: **{prev_d}** 🆚 **{latest_d}**")
            
            # 使用 Streamlit Tab 完全复刻 Excel Sheet 效果
            tab1, tab2, tab3 = st.tabs(["📊 子ASIN - 全部波动", "📦 父ASIN - 全部波动", "🗓️ 父ASIN - weekly波动预警"])
            
            with tab1:
                st.subheader("🛒 子 ASIN 级全要素波动表（按销量波动绝对值降序）")
                st.dataframe(df_sheet1, use_container_width=True, height=550)
                
            with tab2:
                st.subheader("📦 父 ASIN 聚合层级全要素波动看板")
                st.dataframe(df_sheet2, use_container_width=True, height=550)
                
            with tab3:
                st.subheader("🗓️ 周度滚动环比(Weekly)趋势诊断分析")
                st.dataframe(df_sheet3, use_container_width=True, height=550)
                
        except Exception as e:
            st.error(f"💥 矩阵计算解析错误。错误诊断：{e}")
