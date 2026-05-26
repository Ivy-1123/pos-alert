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
# 【更新点】：同时支持 xlsx 和 csv，再也不会因为格式报错了
uploaded_file = st.file_uploader("📂 请上传 VC ASIN 数据表 (支持 Excel 或 CSV 格式)", type=['xlsx', 'csv'])

if uploaded_file is not None:
    with st.spinner('正在执行数据清洗与预警分析...'):
        try:
            # 1. 读取数据 (header=0 完美解决找不到日期表头的Bug)
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file, header=0, low_memory=False)
            else:
                df = pd.read_excel(uploaded_file, header=0)
            
            # 向下填充 Parent ASIN (第0列)
            df.iloc[:, 0] = df.iloc[:, 0].ffill()
            
            # 2. 强制数据过滤 (根据文档的排除规则)
            exclude_status = ['discontinued', 'temp discontinued']
            exclude_div = ['FUR', 'LGT', 'ART', 'APL', 'PET', 'PETB']
            
            # 过滤 RetailStatus (Col 18), Division (Col 3), OM (Col 11)
            df = df[~df.iloc[:, 18].astype(str).str.lower().isin(exclude_status)]
            df = df[~df.iloc[:, 3].astype(str).isin(exclude_div)]
            df = df[df.iloc[:, 11].astype(str).str.lower() != 'discontinued']
            
            # 3. 智能探测最近两天的数据列 (基于 offset)
            date_columns = []
            for i, col in enumerate(df.columns):
                try:
                    pd.to_datetime(col)
                    if i > 30:  # 确保是从第30列之后抓取日期
                        date_columns.append((i, pd.to_datetime(col)))
                except:
                    pass
            
            date_columns_sorted = sorted(date_columns, key=lambda x: x[1], reverse=True)
            
            if len(date_columns_sorted) < 2:
                st.error("❌ 数据文件中未能找到至少 2 天的有效日期列！")
            else:
                latest_idx, latest_date = date_columns_sorted[0]
                prev_idx, prev_date = date_columns_sorted[1]
                
                st.success(f"✅ 成功锁定对比日期: **{latest_date.date()}** vs **{prev_date.date()}**")
                
                # 4. 提取核心数据
                result_data = []
                for index, row in df.iterrows():
                    parent_asin = row.iloc[0]
                    asin = row.iloc[1]
                    om = row.iloc[11]
                    
                    # 基于文档 Offset 提取 Sales (Offset + 6)
                    sales_latest = row.iloc[latest_idx + 6]
                    sales_prev = row.iloc[prev_idx + 6]
                    
                    # 处理空值及转为数字格式，防止计算报错
                    sales_latest = 0 if pd.isna(sales_latest) else float(sales_latest)
                    sales_prev = 0 if pd.isna(sales_prev) else float(sales_prev)
                    
                    avg_sales = (sales_latest + sales_prev) / 2
                    sales_change = sales_latest - sales_prev
                    
                    # 模拟 L30D 均销 (此处简化取两日均值，如有需要后续可扩展)
                    l30d_avg = avg_sales 
                    
                    # 触发预警判定
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
                
                # 5. 在网页上渲染结果表格
                result_df = pd.DataFrame(result_data)
                
                if not result_df.empty:
                    # 按照波动绝对值降序排序
                    result_df['绝对波动'] = result_df['销量波动'].abs()
                    result_df = result_df.sort_values(by='绝对波动', ascending=False).drop(columns=['绝对波动'])
                    
                    st.write("### 🚨 触发预警的 ASIN 列表 (TOP 波动)")
                    
                    # 定义网页端颜色高亮样式
                    def highlight_alert(val):
                        if isinstance(val, str):
                            if '🔴' in val: return 'background-color: #FFC7CE; color: #9C0006; font-weight: bold'
                            if '⚠️' in val: return 'background-color: #FFEB9C; color: #9C6500'
                            if '⚪' in val: return 'background-color: #F2F2F2; color: #333333'
                            if 'ℹ️' in val: return 'background-color: #DDEBF7; color: #004E82'
                        return ''
                    
                    # 渲染带颜色的 DataFrame
                    st.dataframe(result_df.style.map(highlight_alert, subset=['预警层级']), use_container_width=True)
                else:
                    st.info("🎉 今日无异常波动产品。")
                    
        except Exception as e:
            st.error(f"❌ 读取文件或分析数据时发生错误，请检查文件格式。具体报错：{e}")
