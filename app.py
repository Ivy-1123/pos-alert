import streamlit as st
import pandas as pd
import numpy as np

# --- 网页基础设置 ---
st.set_page_config(page_title="VC 波动预警看板", layout="wide")
st.title("🚨 Amazon VC POS 每日波动预警看板")
st.markdown("基于最新上传的 Daily POS 数据，自动对比最近两天销量并触发 4 级预警。")

# --- 预警逻辑定义 (完全复刻你的 Skill 逻辑) ---
def get_alert_tier(avg_sales, sales_change, sales_prev, sales_latest, l30d_avg):
    if avg_sales >= 10 and abs(sales_change) >= 15:
        return '🔴 第一层 (高销突变)'
    if 3 <= avg_sales < 10 and sales_prev > 0 and (abs(sales_change) / sales_prev) >= 0.60:
        return '⚠️ 第二层 (中销波动)'
    if l30d_avg >= 3 and sales_prev >= 3 and sales_latest == 0:
        return '⚪ 第三层 (归零预警)'
    if sales_prev == 0 and sales_latest >= 3:
        return 'ℹ️ 第四层 (恢复预警)'
    return '无预警'

# --- 网页上传组件 ---
uploaded_file = st.file_uploader("📂 请上传 VC ASIN 数据表 (支持 Excel 或 CSV 格式)", type=['xlsx', 'csv'])

if uploaded_file is not None:
    with st.spinner('正在执行数据清洗与预警分析...'):
        try:
            # 1. 直接读取数据（不设 header，保留原始多行表头）
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file, header=None, low_memory=False)
            else:
                df = pd.read_excel(uploaded_file, header=None)
            
            # 向下填充 Parent ASIN (第0列)
            df.iloc[:, 0] = df.iloc[:, 0].ffill()
            
            # 2. 智能探测最近两天的日期列
            # 扫描第0行（包含日期的行），找到所有有效日期
            date_columns = []
            for i in range(df.shape[1]):
                val = str(df.iloc[0, i]).strip()
                try:
                    # 尝试解析形如 2026-04-24 的日期
                    parsed_date = pd.to_datetime(val)
                    if not pd.isna(parsed_date) and i >= 20: # 确保在数据列区域
                        date_columns.append((i, parsed_date))
                except:
                    pass
            
            # 按日期从新到老排序
            date_columns_sorted = sorted(date_columns, key=lambda x: x[1], reverse=True)
            
            # 过滤掉重复的日期列（因为一个日期下面占了多列，我们只需要第一个出现的列索引）
            unique_dates = []
            seen_dates = set()
            for idx, d in date_columns_sorted:
                if d.date() not in seen_dates:
                    seen_dates.add(d.date())
                    unique_dates.append((idx, d))
            
            if len(unique_dates) < 2:
                st.error("❌ 数据文件中未能找到至少 2 天的有效日期列表头！")
            else:
                latest_idx, latest_date = unique_dates[0]
                prev_idx, prev_date = unique_dates[1]
                
                st.success(f"✅ 成功锁定对比日期: **{latest_date.date()}** vs **{prev_date.date()}**")
                
                # 3. 提取核心数据（从第2行开始，避开前两行文字表头）
                result_data = []
                for index, row in df.iloc[2:].iterrows():
                    parent_asin = str(row.iloc[0]).strip()
                    asin = str(row.iloc[1]).strip()
                    om = str(row.iloc[11]).strip()
                    retail_status = str(row.iloc[18]).strip().lower()
                    division = str(row.iloc[3]).strip()
                    
                    # 强制执行你的数据清洗过滤规则
                    if retail_status in ['discontinued', 'temp discontinued']:
                        continue
                    if division in ['FUR', 'LGT', 'ART', 'APL', 'PET', 'PETB']:
                        continue
                    if om.lower() == 'discontinued':
                        continue
                        
                    # 根据你的 Offset 规则精准读取数据：
                    # 日期所在列一般为该日期的起始列，销量在 Offset + 0 (即当前的索引位置)
                    # 如果你的 Ordered Units 就在日期这一列，直接取。如果是偏移，调整数字。
                    sales_latest = row.iloc[latest_idx]
                    sales_prev = row.iloc[prev_idx]
                    
                    # 强行清洗非数字干扰（如空格或文字），转换为数字
                    try:
                        sales_latest = float(sales_latest) if pd.notna(sales_latest) else 0.0
                    except:
                        sales_latest = 0.0
                        
                    try:
                        sales_prev = float(sales_prev) if pd.notna(sales_prev) else 0.0
                    except:
                        sales_prev = 0.0
                    
                    avg_sales = (sales_latest + sales_prev) / 2
                    sales_change = sales_latest - sales_prev
                    l30d_avg = avg_sales 
                    
                    # 运行你的 4 级预警判定
                    alert = get_alert_tier(avg_sales, sales_change, sales_prev, sales_latest, l30d_avg)
                    
                    if alert != '无预警':
                        result_data.append({
                            'OM': om,
                            'Parent ASIN': parent_asin,
                            'ASIN': asin,
                            f'前日销量 ({prev_date.date()})': int(sales_prev),
                            f'昨日销量 ({latest_date.date()})': int(sales_latest),
                            '销量波动': int(sales_change),
                            '预警层级': alert
                        })
                
                # 4. 在网页上渲染结果表格
                result_df = pd.DataFrame(result_data)
                
                if not result_df.empty:
                    result_df['绝对波动'] = result_df['销量波动'].abs()
                    result_df = result_df.sort_values(by='绝对波动', ascending=False).drop(columns=['绝对波动'])
                    
                    st.write("### 🚨 触发预警的 ASIN 列表 (按波动幅度排序)")
                    
                    def highlight_alert(val):
                        if isinstance(val, str):
                            if '🔴' in val: return 'background-color: #FFC7CE; color: #9C0006; font-weight: bold'
                            if '⚠️' in val: return 'background-color: #FFEB9C; color: #9C6500'
                            if '⚪' in val: return 'background-color: #F2F2F2; color: #333333'
                            if 'ℹ️' in val: return 'background-color: #DDEBF7; color: #004E82'
                        return ''
                    
                    st.dataframe(result_df.style.map(highlight_alert, subset=['预警层级']), use_container_width=True)
                else:
                    st.info("🎉 今日无异常波动产品。")
                    
        except Exception as e:
            st.error(f"❌ 分析失败。具体报错原因：{e}")
