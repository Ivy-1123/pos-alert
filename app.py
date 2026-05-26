import streamlit as st
import pandas as pd
import numpy as np

# --- 网页基础设置 ---
st.set_page_config(page_title="VC POS 波动预警终极版", layout="wide")
st.title("🚨 Amazon VC POS 销售波动预警报告系统 (SOP 像素级还原版)")
st.markdown("严格对齐原始 md 规范，支持 7 指标全维监控、4-Tier 预警算法、Revenue Impact 震荡分级及多 Sheet 排行。")

# --- 核心辅助计算函数 ---
def safe_float(val):
    if pd.isna(val) or str(val).strip() == '' or str(val).strip().lower() == 'nan':
        return 0.0
    try:
        return float(str(val).replace('%', '').replace(',', '').strip())
    except:
        return 0.0

# 1. 严格复刻 4-Tier 预警算法
def get_alert_tier_info(avg_sales, sales_change, sales_prev, sales_latest, l30d_avg):
    # 第一层：高销量产品大幅突变
    if avg_sales >= 10 and abs(sales_change) >= 15:
        return '🔴 High', f'高销量产品大幅突变: 平均销量{avg_sales:.0f}≥10且变化{abs(sales_change):.0f}≥15件'
    # 第二层：中销量产品大幅波动
    if 3 <= avg_sales < 10 and sales_prev > 0:
        change_rate = abs(sales_change) / sales_prev
        if change_rate >= 0.60:
            return '⚠️ Medium', f'中销量产品大幅波动: 平均销量{avg_sales:.1f}在3-10且变化率{change_rate:.1%}≥60%'
    # 第三层：活跃链接归零预警
    if l30d_avg >= 3 and sales_prev >= 3 and sales_latest == 0:
        return '⚪ Low', f'活跃链接归零预警: L30D≥3且前日{sales_prev:.0f}≥3且昨日归零'
    # 第四层：归零后恢复预警
    if sales_prev == 0 and sales_latest >= 3:
        return 'ℹ️ Info', f'归零后恢复预警: 前日归零但昨日恢复至{sales_latest:.0f}≥3'
    return None, '正常'

# 2. 严格复刻 Revenue Impact 影响级别分类
def get_revenue_impact_level(impact_val):
    impact_abs = abs(impact_val)
    if impact_abs >= 5000: return 'S'
    elif impact_abs >= 1000: return 'A'
    elif impact_abs >= 500:  return 'B'
    elif impact_abs >= 100:  return 'C'
    return 'D'

# 3. 严格复刻趋势符号引擎
def get_trend_symbol(val_day2, val_day1, is_pct=False):
    diff = val_day2 - val_day1
    if is_pct:
        # 针对百分比指标，波动绝对值超 0.1% 认定为有趋势
        if diff > 0.001: return '↑'
        elif diff < -0.001: return '↓'
        return '→'
    else:
        if diff > 0.02: return '↑'
        elif diff < -0.02: return '↓'
        return '→'

# 4. 生成规范要求的波动驱动因素文本
def build_driving_factors_text(s_chg, g_chg, p_chg, c_chg, sp_chg, tc_chg):
    def sym(c): return '↑' if c > 0 else ('↓' if c < 0 else '→')
    return f"销量{sym(s_chg)} GV{sym(g_chg)} 价格{sym(p_chg)} CVR{sym(c_chg)} SPSD{sym(sp_chg)} TACOS{sym(tc_chg)}"

# --- 网页上传组件 ---
uploaded_file = st.file_uploader("📂 请上传原始 VC ASIN 复合数据表 (支持 xlsx 或 csv)", type=['xlsx', 'csv'])

if uploaded_file is not None:
    with st.spinner('🔥 正在清洗噪音、横向探测 7 组核心偏移量并处理 14 天周滚动趋势...'):
        try:
            # 1. 载入原始大表
            if uploaded_file.name.endswith('.csv'):
                raw_df = pd.read_csv(uploaded_file, header=None, low_memory=False)
            else:
                raw_df = pd.read_excel(uploaded_file, header=None)
            
            # 向下填充 Parent ASIN (第0列)
            raw_df.iloc[:, 0] = raw_df.iloc[:, 0].ffill()
            
            # 2. 多行复合表头深度定位 (探测大盘中所有日期和指标对齐块)
            date_row = raw_df.iloc[0, :]
            sub_header_row = raw_df.iloc[1, :]
            
            date_blocks = {}
            unique_dates = []
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
                            unique_dates.append(current_date)
                except:
                    pass
                
                if current_date is not None:
                    # 精准对齐 7 大核心财务和运营指标在日期块下的相对坐标
                    if 'ordered units' in sub_val or sub_val == '0': date_blocks[current_date]['units'] = col_idx
                    elif 'views' in sub_val or 'gv' in sub_val: date_blocks[current_date]['gv'] = col_idx
                    elif 'asp' in sub_val or 'price' in sub_val or 'average retail price' in sub_val: date_blocks[current_date]['price'] = col_idx
                    elif 'spsd' in sub_val or 'sp spend' in sub_val: date_blocks[current_date]['spsd'] = col_idx
                    elif 'sbdsp' in sub_val or 'sb spend' in sub_val: date_blocks[current_date]['sbdsp'] = col_idx
                    elif 'cvr' in sub_val or 'conversion rate' in sub_val: date_blocks[current_date]['cvr'] = col_idx
                    elif 'tacos' in sub_val: date_blocks[current_date]['tacos'] = col_idx
                    elif 'revenue' in sub_val or 'sales' in sub_val: date_blocks[current_date]['revenue'] = col_idx

            sorted_dates = sorted(unique_dates, reverse=True)
            if len(sorted_dates) < 2:
                st.error("❌ 数据源横向解析失败：未检测到至少 2 天的有效历史日期块！")
                st.stop()
                
            latest_d, prev_d = sorted_dates[0], sorted_dates[1]
            
            # --- 3. 纵向漏斗清洗（严格阻击总计行、空白行和特定退市部门） ---
            cleaned_rows = []
            for idx, row in raw_df.iloc[2:].iterrows():
                parent_asin = str(row.iloc[0]).strip()
                asin = str(row.iloc[1]).strip()
                division = str(row.iloc[3]).strip()
                brand = str(row.iloc[4]).strip()
                om = str(row.iloc[11]).strip()
                retail_status = str(row.iloc[18]).strip().lower()
                
                # 核心风控排除拦截器
                if parent_asin.lower() in ['total', '总计', 'nan', '']: continue
                if asin.lower() in ['total', '总计', 'nan', '', 'asin']: continue
                if retail_status in ['discontinued', 'temp discontinued']: continue
                if division in ['FUR', 'LGT', 'ART', 'APL', 'PET', 'PETB']: continue
                if om.lower() == 'discontinued': continue
                
                cleaned_rows.append(row)
                
            if not cleaned_rows:
                st.warning("⚠️ 经过过滤条件执行后，未留下任何有效 ASIN 产品明细！")
                st.stop()

            # --- 4. 子 ASIN 基础数据建模与多指标横向扫描计算 ---
            child_list = []
            for row in cleaned_rows:
                parent_asin = str(row.iloc[0]).strip()
                asin = str(row.iloc[1]).strip()
                item_no = str(row.iloc[2]).strip()
                division = str(row.iloc[3]).strip()
                brand = str(row.iloc[4]).strip()
                category = str(row.iloc[5]).strip()
                subcat = str(row.iloc[6]).strip()
                pattern = str(row.iloc[7]).strip()
                color = str(row.iloc[8]).strip()
                size = str(row.iloc[9]).strip()
                om = str(row.iloc[11]).strip()
                buckets = str(row.iloc[12]).strip()
                class_code = str(row.iloc[13]).strip()
                prod_tag = str(row.iloc[15]).strip()
                retail_status = str(row.iloc[18]).strip()
                
                # 安全提取 T日 与 T-1 日 7 指标原生数值
                b_l = date_blocks[latest_d]
                b_p = date_blocks[prev_d]
                
                u_l = safe_float(row.iloc[b_l['units']])
                u_p = safe_float(row.iloc[b_p['units']])
                gv_l = safe_float(row.iloc[b_l.get('gv', b_l['units'])])
                gv_p = safe_float(row.iloc[b_p.get('gv', b_p['units'])])
                pr_l = safe_float(row.iloc[b_l.get('price', b_l['units'])])
                pr_p = safe_float(row.iloc[b_p.get('price', b_p['units'])])
                sp_l = safe_float(row.iloc[b_l.get('spsd', b_l['units'])])
                sp_p = safe_float(row.iloc[b_p.get('spsd', b_p['units'])])
                sb_l = safe_float(row.iloc[b_l.get('sbdsp', b_l['units'])])
                sb_p = safe_float(row.iloc[b_p.get('sbdsp', b_p['units'])])
                cv_l = safe_float(row.iloc[b_l.get('cvr', b_l['units'])])
                cv_p = safe_float(row.iloc[b_p.get('cvr', b_p['units'])])
                tc_l = safe_float(row.iloc[b_l.get('tacos', b_l['units'])])
                tc_p = safe_float(row.iloc[b_p.get('tacos', b_p['units'])])
                rev_p = safe_float(row.iloc[b_p.get('revenue', b_p['units'])])
                
                # 计算真实的过去30天日均销量 (L30D)
                hist_units = []
                for d in sorted_dates[:30]:
                    if 'units' in date_blocks[d]:
                        hist_units.append(safe_float(row.iloc[date_blocks[d]['units']]))
                l30d_avg = np.mean(hist_units) if hist_units else 0.0
                
                # 运行 4-Tier 核心判定
                avg_sales = (u_p + u_l) / 2
                sales_change = u_l - u_p
                tier, reason = get_alert_tier_info(avg_sales, sales_change, u_p, u_l, l30d_avg)
                
                # 计算 Revenue Impact 震荡表现
                rev_impact = sales_change * pr_l
                impact_pct = (rev_impact / rev_p * 100) if rev_p > 0 else 0.0
                fmt_impact = f"{'+' if rev_impact >= 0 else ''}${rev_impact:,.2f} ({'+' if impact_pct >= 0 else ''}{impact_pct:.1f}%)"
                impact_level = get_revenue_impact_level(rev_impact)
                
                driving = build_driving_factors_text(sales_change, gv_l - gv_p, pr_l - pr_p, cv_l - cv_p, sp_l - sp_p, tc_l - tc_p)
                
                child_list.append({
                    'Parent ASIN': parent_asin, 'ASIN': asin, 'ItemNo': item_no, 'Division': division, 'Brand': brand,
                    'Category': category, 'Subcategory': subcat, 'Pattern': pattern, 'Color': color, 'Size': size,
                    'OM': om, 'BucketsList': buckets, 'ClassificationCode': class_code, 'ProductTag': prod_tag, 'Retail Status': retail_status,
                    'L30D销量均值': l30d_avg, 'units_p': u_p, 'units_l': u_l, 'gv_p': gv_p, 'gv_l': gv_l, 'price_p': pr_p, 'price_l': pr_l,
                    'cvr_p': cv_p, 'cvr_l': cv_l, 'spsd_p': sp_p, 'spsd_l':
