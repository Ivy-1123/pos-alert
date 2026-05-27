import streamlit as st
import pandas as pd
import numpy as np
import io
import os
from datetime import datetime

# --- 网页基础设置 ---
st.set_page_config(page_title="VC POS 波动预警终极版", layout="wide", initial_sidebar_state="expanded")
st.title("🚨 Amazon VC POS 销售波动预警看板 (全自动企业版)")
st.markdown("本看板已接入云端自动同步引擎。**每天只需管理员将最新数据覆盖至系统，全员即可共享 6 大维度的秒级联动过滤与完美字段排版的 Excel 导出。**")

# --- 核心辅助计算函数 ---
def safe_float(val):
    if pd.isna(val) or str(val).strip() == '' or str(val).strip().lower() == 'nan':
        return 0.0
    try:
        return float(str(val).replace('%', '').replace(',', '').strip())
    except:
        return 0.0

def get_alert_tier_info(avg_sales, sales_change, sales_prev, sales_latest, l30d_avg):
    if avg_sales >= 10 and abs(sales_change) >= 15:
        return '🔴 High', f'高销量突变: 均销{avg_sales:.0f}≥10且变化{abs(sales_change):.0f}≥15'
    if 3 <= avg_sales < 10 and sales_prev > 0:
        change_rate = abs(sales_change) / sales_prev
        if change_rate >= 0.60:
            return '⚠️ Medium', f'中销量波动: 均销{avg_sales:.1f}在3-10且波动率{change_rate:.1%}≥60%'
    if l30d_avg >= 3 and sales_prev >= 3 and sales_latest == 0:
        return '⚪ Low', f'活跃链接归零: L30D≥3且前日{sales_prev:.0f}≥3且昨日=0'
    if sales_prev == 0 and sales_latest >= 3:
        return 'ℹ️ Info', f'归零后恢复: 前日=0且昨日恢复至{sales_latest:.0f}≥3'
    return None, '正常'

def get_revenue_impact_level(impact_val):
    impact_abs = abs(impact_val)
    if impact_abs >= 5000: return 'S'
    elif impact_abs >= 1000: return 'A'
    elif impact_abs >= 500:  return 'B'
    elif impact_abs >= 100:  return 'C'
    return 'D'

def get_trend_symbol(val_day2, val_day1, is_pct=False):
    diff = val_day2 - val_day1
    if is_pct:
        if diff > 0.001: return '↑'
        elif diff < -0.001: return '↓'
        return '→'
    else:
        if diff > 0.02: return '↑'
        elif diff < -0.02: return '↓'
        return '→'

def build_driving_factors_text(s_chg, g_chg, p_chg, c_chg, sp_chg, tc_chg):
    def sym(c): return '↑' if c > 0 else ('↓' if c < 0 else '→')
    return f"销量{sym(s_chg)} GV{sym(g_chg)} 价格{sym(p_chg)} CVR{sym(c_chg)} SPSD{sym(sp_chg)} TACOS{sym(tc_chg)}"

# ==================== 🚀 核心更新：POS 数据读取缓存引擎 ====================
@st.cache_data(show_spinner=False)
def load_and_parse_data(file_bytes, file_name):
    if file_name.endswith('.csv'):
        raw_df = pd.read_csv(io.BytesIO(file_bytes), header=None, low_memory=False)
    else:
        raw_df = pd.read_excel(io.BytesIO(file_bytes), header=None)
    
    raw_df.iloc[:, 0] = raw_df.iloc[:, 0].ffill()
    
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
        return None, None, None, "❌ 数据源横向解析失败：未检测到至少 2 天的有效历史日期块！"
        
    latest_d, prev_d = sorted_dates[0], sorted_dates[1]
    
    cleaned_rows = []
    for idx, row in raw_df.iloc[2:].iterrows():
        parent_asin = str(row.iloc[0]).strip()
        asin = str(row.iloc[1]).strip()
        division = str(row.iloc[3]).strip()
        om = str(row.iloc[11]).strip()
        retail_status = str(row.iloc[18]).strip().lower()
        
        if parent_asin.lower() in ['total', '总计', 'nan', '']: continue
        if asin.lower() in ['total', '总计', 'nan', '', 'asin']: continue
        if retail_status in ['discontinued', 'temp discontinued']: continue
        if division in ['FUR', 'LGT', 'ART', 'APL', 'PET', 'PETB']: continue
        if om.lower() == 'discontinued': continue
        cleaned_rows.append(row)
        
    if not cleaned_rows:
        return None, None, None, "⚠️ 过滤后未留下任何有效明细！"

    child_list = []
    for row in cleaned_rows:
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
        
        hist_units = [safe_float(row.iloc[date_blocks[d]['units']]) for d in sorted_dates[:30] if 'units' in date_blocks[d]]
        l30d_avg = np.mean(hist_units) if hist_units else 0.0
        
        avg_sales = (u_p + u_l) / 2
        sales_change = u_l - u_p
        tier, reason = get_alert_tier_info(avg_sales, sales_change, u_p, u_l, l30d_avg)
        
        rev_impact = sales_change * pr_l
        impact_pct = (rev_impact / rev_p * 100) if rev_p > 0 else 0.0
        fmt_impact = f"{'+' if rev_impact >= 0 else ''}${rev_impact:,.2f} ({'+' if impact_pct >= 0 else ''}{impact_pct:.1f}%)"
        
        driving = build_driving_factors_text(sales_change, gv_l - gv_p, pr_l - pr_p, cv_l - cv_p, sp_l - sp_p, tc_l - tc_p)
        
        child_list.append({
            'Parent ASIN': str(row.iloc[0]).strip(), 'ASIN': str(row.iloc[1]).strip(), 'ItemNo': str(row.iloc[2]).strip(), 
            'Division': str(row.iloc[3]).strip(), 'Brand': str(row.iloc[4]).strip(),
            'Category': str(row.iloc[5]).strip(), 'Subcategory': str(row.iloc[6]).strip(), 
            'Pattern': str(row.iloc[7]).strip(), 'Color': str(row.iloc[8]).strip(), 'Size': str(row.iloc[9]).strip(),
            'OM': str(row.iloc[11]).strip(), 'BucketsList': str(row.iloc[12]).strip(), 
            'ClassificationCode': str(row.iloc[13]).strip(), 'ProductTag': str(row.iloc[15]).strip(), 'Retail Status': str(row.iloc[18]).strip(),
            'L30D销量均值': l30d_avg, 'units_p': u_p, 'units_l': u_l, 'gv_p': gv_p, 'gv_l': gv_l, 'price_p': pr_p, 'price_l': pr_l,
            'cvr_p': cv_p, 'cvr_l': cv_l, 'spsd_p': sp_p, 'spsd_l': sp_l, 'sbdsp_p': sb_p, 'sbdsp_l': sb_l, 'tacos_p': tc_p, 'tacos_l': tc_l,
            'Revenue_Impact': fmt_impact, '影响级别': get_revenue_impact_level(rev_impact), '预警层级': tier if tier else '无预警', '预警原因': reason, '波动驱动因素': driving,
            'raw_row_data': row, 'rev_p': rev_p, 'rev_l': u_l * pr_l
        })
        
    df_child_master_cached = pd.DataFrame(child_list)
    return df_child_master_cached, sorted_dates, date_blocks, None

# ==================== 📡 POS 自动读取引擎 ====================
file_path_xlsx = "today_data.xlsx"
file_path_csv = "today_data.csv"
target_file = None

if os.path.exists(file_path_xlsx): target_file = file_path_xlsx
elif os.path.exists(file_path_csv): target_file = file_path_csv

if target_file is None:
    st.error("🛑 系统未检测到 POS 数据源文件！")
    st.info("💡 **管理员指南**：请将最新的亚马逊 VC POS 报表重命名为 `today_data.xlsx` (或 .csv)，然后上传覆盖到您的 GitHub 仓库根目录。刷新网页即可自动读取。")
    st.stop()

mtime = os.path.getmtime(target_file)
last_updated_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

with st.spinner('🔥 正在从云端加载 POS 基础数据并执行预警算法...'):
    try:
        with open(target_file, "rb") as f:
            file_bytes = f.read()
            
        df_child_cached, sorted_dates, date_blocks, err_msg = load_and_parse_data(file_bytes, target_file)
        
        if err_msg:
            st.error(err_msg)
            st.stop()
            
        latest_d, prev_d = sorted_dates[0], sorted_dates[1]
        
        if len(sorted_dates) >= 14:
            w2_days, w1_days = sorted_dates[:7], sorted_dates[7:14]
            w2_str = f"{w2_days[-1]} ~ {w2_days[0]}"
            w1_str = f"{w1_days[-1]} ~ {w1_days[0]}"
            weekly_banner_text = f"**WK1 (上周)**: {w1_str} 🆚 **WK2 (本周)**: {w2_str}"
        else:
            w2_days, w1_days = [], []
            weekly_banner_text = "数据天数不足 14 天，暂无周对比区间"

        st.info(f"🕒 **数据最后同步时间**: `{last_updated_str}` \n\n"
                f"📅 **Daily (日度对比区间)** ➔ **D1 (前日)**: `{prev_d}` 🆚 **D2 (昨日)**: `{latest_d}` \n\n"
                f"📆 **Weekly (周度对比区间)** ➔ {weekly_banner_text}")

        df_child_master = df_child_cached.copy()

        # ==================== 🎛️ 侧边栏 6 大多维过滤引擎 ====================
        st.sidebar.header("🔍 数据多维侧边栏过滤")
        st.sidebar.markdown("支持多选，留空即为查看全盘数据。")
        
        def get_options(col_name):
            return sorted([str(x) for x in df_child_master[col_name].unique() if pd.notna(x) and str(x).strip() != ''])
            
        om_options = get_options('OM')
        pattern_options = get_options('Pattern')
        bucket_options = get_options('BucketsList')
        tag_options = get_options('ProductTag')
        cat_options = get_options('Category')
        subcat_options = get_options('Subcategory')
        
        selected_oms = st.sidebar.multiselect("👨‍💼 筛选 OM", options=om_options)
        selected_patterns = st.sidebar.multiselect("🎨 筛选 Pattern", options=pattern_options)
        selected_buckets = st.sidebar.multiselect("🪣 筛选 BucketsList", options=bucket_options)
        selected_tags = st.sidebar.multiselect("🏷️ 筛选 ProductTag", options=tag_options)
        selected_cats = st.sidebar.multiselect("📁 筛选 Category", options=cat_options)
        selected_subcats = st.sidebar.multiselect("📂 筛选 Subcategory", options=subcat_options)
        
        # 执行过滤
        if selected_oms: df_child_master = df_child_master[df_child_master['OM'].astype(str).isin(selected_oms)]
        if selected_patterns: df_child_master = df_child_master[df_child_master['Pattern'].astype(str).isin(selected_patterns)]
        if selected_buckets: df_child_master = df_child_master[df_child_master['BucketsList'].astype(str).isin(selected_buckets)]
        if selected_tags: df_child_master = df_child_master[df_child_master['ProductTag'].astype(str).isin(selected_tags)]
        if selected_cats: df_child_master = df_child_master[df_child_master['Category'].astype(str).isin(selected_cats)]
        if selected_subcats: df_child_master = df_child_master[df_child_master['Subcategory'].astype(str).isin(selected_subcats)]
        
        if df_child_master.empty:
            st.warning("⚠️ 在当前的筛选组合下，没有匹配到任何数据，请在左侧栏重新调整条件。")
            st.stop()

        # ==================== 🛠️ 1. 子 ASIN 完整字段拼装 (严格对齐顺序) ====================
        s2_s3_rows = []
        for idx, r in df_child_master.iterrows():
            s2_s3_rows.append({
                # --- 产品基础信息 (严格15字段) ---
                'Parent ASIN': r['Parent ASIN'], 'ASIN': r['ASIN'], 'ItemNo': r['ItemNo'], 'Division': r['Division'], 
                'Brand': r['Brand'], 'Category': r['Category'], 'Subcategory': r['Subcategory'], 'Pattern': r['Pattern'], 
                'Color': r['Color'], 'Size': r['Size'], 'OM': r['OM'], 'BucketsList': r['BucketsList'], 
                'ClassificationCode': r['ClassificationCode'], 'ProductTag': r['ProductTag'],
                # --- 核心指标信息 ---
                'Retail Status': r['Retail Status'], 'L30D销量均值': int(r['L30D销量均值']),
                '预警层级': r['预警层级'], '影响级别': r['影响级别'], 'Revenue_Impact': r['Revenue_Impact'],
                '销量_D1': int(r['units_p']), '销量_D2': int(r['units_l']), '销量变化': int(r['units_l'] - r['units_p']), '销量变化率': (r['units_l'] - r['units_p'])/r['units_p'] if r['units_p'] > 0 else 0.0, '销量趋势': get_trend_symbol(r['units_l'], r['units_p']),
                'GV_D1': int(r['gv_p']), 'GV_D2': int(r['gv_l']), 'GV变化': int(r['gv_l'] - r['gv_p']), 'GV变化率': (r['gv_l'] - r['gv_p'])/r['gv_p'] if r['gv_p'] > 0 else 0.0, 'GV趋势': get_trend_symbol(r['gv_l'], r['gv_p']),
                '价格_D1': r['price_p'], '价格_D2': r['price_l'], '价格变化': r['price_l'] - r['price_p'], '价格变化率': (r['price_l'] - r['price_p'])/r['price_p'] if r['price_p'] > 0 else 0.0, '价格趋势': get_trend_symbol(r['price_l'], r['price_p']),
                'CVR_D1': r['cvr_p'], 'CVR_D2': r['cvr_l'], 'CVR变化': r['cvr_l'] - r['cvr_p'], 'CVR变化率': (r['cvr_l'] - r['cvr_p'])/r['cvr_p'] if r['cvr_p'] > 0 else 0.0, 'CVR趋势': get_trend_symbol(r['cvr_l'], r['cvr_p'], True),
                'SPSD_D1': int(r['spsd_p']), 'SPSD_D2': int(r['spsd_l']), 'SPSD变化': int(r['spsd_l'] - r['spsd_p']), 'SPSD变化率': (r['spsd_l'] - r['spsd_p'])/r['spsd_p'] if r['spsd_p'] > 0 else 0.0, 'SPSD趋势': get_trend_symbol(r['spsd_l'], r['spsd_p']),
                'SBDSP_D1': int(r['sbdsp_p']), 'SBDSP_D2': int(r['sbdsp_l']), 'SBDSP变化': int(r['sbdsp_l'] - r['sbdsp_p']), 'SBDSP变化率': (r['sbdsp_l'] - r['sbdsp_p'])/r['sbdsp_p'] if r['sbdsp_p'] > 0 else 0.0, 'SBDSP趋势': get_trend_symbol(r['sbdsp_l'], r['sbdsp_p']),
                'TACOS_D1': r['tacos_p'], 'TACOS_D2': r['tacos_l'], 'TACOS变化': r['tacos_l'] - r['tacos_p'], 'TACOS变化率': (r['tacos_l'] - r['tacos_p'])/r['tacos_p'] if r['tacos_p'] > 0 else 0.0, 'TACOS趋势': get_trend_symbol(r['tacos_l'], r['tacos_p'], True),
                '预警原因': r['预警原因'], '波动驱动因素': r['波动驱动因素'],
                'u_diff': abs(r['units_l'] - r['units_p'])
            })
            
        df_s3_all = pd.DataFrame(s2_s3_rows)
        df_s3_alert = df_s3_all[df_s3_all['预警层级'] != '无预警'].sort_values(by='u_diff', ascending=False).drop(columns=['u_diff']).reset_index(drop=True)
        df_s3_alert.insert(0, 'Rank', df_s3_alert.index + 1)
        df_top50_s2 = df_s3_alert.head(50).copy()
        
        # ==================== 🛠️ 2. 父 ASIN 完整字段拼装 (严格对齐顺序) ====================
        parent_group = df_child_master.groupby('Parent ASIN').agg({
            'ASIN': 'nunique', 'Division': 'first', 'Brand': 'first', 'Category': 'first', 'Subcategory': 'first',
            'Pattern': 'first', 'OM': 'first', 'BucketsList': 'first', 'ProductTag': 'first', 'Retail Status': 'first',
            'L30D销量均值': 'sum', 'units_p': 'sum', 'units_l': 'sum', 'gv_p': 'sum', 'gv_l': 'sum',
            'rev_p': 'sum', 'rev_l': 'sum', 'spsd_p': 'sum', 'spsd_l': 'sum', 'sbdsp_p': 'sum', 'sbdsp_l': 'sum'
        }).reset_index()
        
        parent_list = []
        for idx, row in parent_group.iterrows():
            u_p, u_l = row['units_p'], row['units_l']
            gv_p, gv_l = row['gv_p'], row['gv_l']
            rev_p, rev_l = row['rev_p'], row['rev_l']
            sp_p, sp_l = row['spsd_p'], row['spsd_l']
            sb_p, sb_l = row['sbdsp_p'], row['sbdsp_l']
            
            pr_p = (rev_p / u_p) if u_p > 0 else 0.0
            pr_l = (rev_l / u_l) if u_l > 0 else 0.0
            cv_p = (u_p / gv_p) if gv_p > 0 else 0.0
            cv_l = (u_l / gv_l) if gv_l > 0 else 0.0
            tc_p = (sp_p / rev_p) if rev_p > 0 else 0.0
            tc_l = (sp_l / rev_l) if rev_l > 0 else 0.0
            
            p_change = u_l - u_p
            p_tier, p_reason = get_alert_tier_info((u_p+u_l)/2, p_change, u_p, u_l, row['L30D销量均值'])
            p_impact = p_change * pr_l
            p_impact_pct = (p_impact / rev_p * 100) if rev_p > 0 else 0.0
            fmt_p_impact = f"{'+' if p_impact >= 0 else ''}${p_impact:,.2f} ({'+' if p_impact_pct >= 0 else ''}{p_impact_pct:.1f}%)"
            
            parent_list.append({
                # --- 产品基础信息 (严格11字段) ---
                'Parent ASIN': row['Parent ASIN'], 'ASIN Count': int(row['ASIN']), 'Division': row['Division'], 
                'Brand': row['Brand'], 'Category': row['Category'], 'Subcategory': row['Subcategory'], 
                'Pattern': row['Pattern'], 'OM': row['OM'], 'BucketsList': row['BucketsList'], 'ProductTag': row['ProductTag'],
                # --- 核心指标信息 ---
                'Retail Status': row['Retail Status'], 'L30D销量均值': int(row['L30D销量均值']),
                '预警层级': p_tier if p_tier else '无预警', '影响级别': get_revenue_impact_level(p_impact), 'Revenue_Impact': fmt_p_impact, 
                '销量_D1': int(u_p), '销量_D2': int(u_l), '销量变化': int(p_change), '销量变化率': p_change/u_p if u_p > 0 else 0.0, '销量趋势': get_trend_symbol(u_l, u_p),
                'GV_D1': int(gv_p), 'GV_D2': int(gv_l), 'GV变化': int(gv_l - gv_p), 'GV变化率': (gv_l - gv_p)/gv_p if gv_p > 0 else 0.0, 'GV趋势': get_trend_symbol(gv_l, gv_p),
                '价格_D1': pr_p, '价格_D2': pr_l, '价格变化': pr_l - pr_p, '价格变化率': (pr_l - pr_p)/pr_p if pr_p > 0 else 0.0, '价格趋势': get_trend_symbol(pr_l, pr_p),
                'CVR_D1': cv_p, 'CVR_D2': cv_l, 'CVR变化': cv_l - cv_p, 'CVR变化率': (cv_l - cv_p)/cv_p if cv_p > 0 else 0.0, 'CVR趋势': get_trend_symbol(cv_l, cv_p, True),
                'SPSD_D1': int(sp_p), 'SPSD_D2': int(sp_l), 'SPSD变化': int(sp_l - sp_p), 'SPSD变化率': (sp_l - sp_p)/sp_p if sp_p > 0 else 0.0, 'SPSD趋势': get_trend_symbol(sp_l, sp_p),
                'SBDSP_D1': int(sb_p), 'SBDSP_D2': int(sb_l), 'SBDSP变化': int(sb_l - sb_p), 'SBDSP变化率': (sb_l - sb_p)/sb_p if sb_p > 0 else 0.0, 'SBDSP趋势': get_trend_symbol(sb_l, sb_p),
                'TACOS_D1': tc_p, 'TACOS_D2': tc_l, 'TACOS变化': tc_l - tc_p, 'TACOS变化率': (tc_l - tc_p)/tc_p if tc_p > 0 else 0.0, 'TACOS趋势': get_trend_symbol(tc_l, tc_p, True),
                '预警原因': p_reason, '波动驱动因素': build_driving_factors_text(p_change, gv_l - gv_p, pr_l - pr_p, cv_l - cv_p, sp_l - sp_p, tc_l - tc_p),
                'p_u_diff': abs(p_change)
            })
            
        df_s5_alert = pd.DataFrame(parent_list)
        df_s5_alert = df_s5_alert[df_s5_alert['预警层级'] != '无预警'].sort_values(by='p_u_diff', ascending=False).drop(columns=['p_u_diff']).reset_index(drop=True)
        df_s5_alert.insert(0, 'Rank', df_s5_alert.index + 1)
        df_s4_top50 = df_s5_alert.head(50).copy()

        # ==================== 🛠️ 3. Weekly 父 ASIN 完整字段拼装 ====================
        s6_records = []
        if len(sorted_dates) >= 14:
            for idx, p_row in parent_group.iterrows():
                p_asin = p_row['Parent ASIN']
                children = df_child_master[df_child_master['Parent ASIN'] == p_asin]
                
                w1_units, w2_units, w1_gv, w2_gv, w1_rev, w2_rev, w1_sp, w2_sp, w1_sb, w2_sb = 0,0,0,0,0,0,0,0,0,0
                for d in w2_days:
                    if d in date_blocks:
                        b = date_blocks[d]
                        for _, cr in children.iterrows():
                            r = cr['raw_row_data']
                            w2_units += safe_float(r.iloc[b['units']])
                            w2_gv += safe_float(r.iloc[b.get('gv', b['units'])])
                            w2_rev += safe_float(r.iloc[b.get('revenue', b['units'])])
                            w2_sp += safe_float(r.iloc[b.get('spsd', b['units'])])
                            w2_sb += safe_float(r.iloc[b.get('sbdsp', b['units'])])
                            
                for d in w1_days:
                    if d in date_blocks:
                        b = date_blocks[d]
                        for _, cr in children.iterrows():
                            r = cr['raw_row_data']
                            w1_units += safe_float(r.iloc[b['units']])
                            w1_gv += safe_float(r.iloc[b.get('gv', b['units'])])
                            w1_rev += safe_float(r.iloc[b.get('revenue', b['units'])])
                            w1_sp += safe_float(r.iloc[b.get('spsd', b['units'])])
                            w1_sb += safe_float(r.iloc[b.get('sbdsp', b['units'])])
                            
                w1_price = (w1_rev / w1_units) if w1_units > 0 else 0.0
                w2_price = (w2_rev / w2_units) if w2_units > 0 else 0.0
                w1_cvr = (w1_units / w1_gv) if w1_gv > 0 else 0.0
                w2_cvr = (w2_units / w2_gv) if w2_gv > 0 else 0.0
                w1_tacos = (w1_sp / w1_rev) if w1_rev > 0 else 0.0
                w2_tacos = (w2_sp / w2_rev) if w2_rev > 0 else 0.0
                
                w_units_diff = w2_units - w1_units
                w_pct = (w_units_diff / w1_units) if w1_units > 0 else 0.0
                w_alert = '🔴 周销量暴跌' if (w_pct <= -0.30 and w1_units > 20) else ('🚀 周销量暴涨' if w_pct >= 0.30 else '正常')
                
                w_impact = w_units_diff * w2_price
                w_impact_pct = (w_impact / w1_rev * 100) if w1_rev > 0 else 0.0
                fmt_w_impact = f"{'+' if w_impact >= 0 else ''}${w_impact:,.2f} ({'+' if w_impact_pct >= 0 else ''}{w_impact_pct:.1f}%)"
                
                s6_records.append({
                    # --- 严格对齐字段 ---
                    'Parent ASIN': p_asin, 'ASIN Count': int(p_row['ASIN']), 'Division': p_row['Division'], 'Brand': p_row['Brand'],
                    'Category': p_row['Category'], 'Subcategory': p_row['Subcategory'], 'Pattern': p_row['Pattern'], 'OM': p_row['OM'],
                    'BucketsList': p_row['BucketsList'], 'ProductTag': p_row['ProductTag'], 'Retail Status': p_row['Retail Status'],
                    '预警层级': w_alert, '影响级别': get_revenue_impact_level(w_impact), 'Revenue_Impact': fmt_w_impact,
                    '销量_W1': int(w1_units), '销量_W2': int(w2_units), '销量变化': int(w_units_diff), '销量变化率': w_pct, '销量趋势': get_trend_symbol(w2_units, w1_units),
                    'GV_W1': int(w1_gv), 'GV_W2': int(w2_gv), 'GV变化': int(w2_gv - w1_gv), 'GV变化率': (w2_gv - w1_gv)/w1_gv if w1_gv > 0 else 0.0, 'GV趋势': get_trend_symbol(w2_gv, w1_gv),
                    '价格_W1': w1_price, '价格_W2': w2_price, '价格变化': w2_price - w1_price, '价格变化率': (w2_price - w1_price)/w1_price if w1_price > 0 else 0.0, '价格趋势': get_trend_symbol(w2_price, w1_price),
                    'CVR_W1': w1_cvr, 'CVR_W2': w2_cvr, 'CVR变化': w2_cvr - w1_cvr, 'CVR变化率': (w2_cvr - w1_cvr)/w1_cvr if w1_cvr > 0 else 0.0, 'CVR趋势': get_trend_symbol(w2_cvr, w1_cvr, True),
                    'SPSD_W1': int(w1_sp), 'SPSD_W2': int(w2_sp), 'SPSD变化': int(w2_sp - w1_sp), 'SPSD变化率': (w2_sp - w1_sp)/w1_sp if w1_sp > 0 else 0.0, 'SPSD趋势': get_trend_symbol(w2_sp, w1_sp),
                    'SBDSP_W1': int(w1_sb), 'SBDSP_W2': int(w2_sb), 'SBDSP变化': int(w2_sb - w1_sb), 'SBDSP变化率': (w2_sb - w1_sb)/w1_sb if w1_sb > 0 else 0.0, 'SBDSP趋势': get_trend_symbol(w2_sb, w1_sb),
                    'TACOS_W1': w1_tacos, 'TACOS_W2': w2_tacos, 'TACOS变化': w2_tacos - w1_tacos, 'TACOS变化率': (w2_tacos - w1_tacos)/w1_tacos if w1_tacos > 0 else 0.0, 'TACOS趋势': get_trend_symbol(w2_tacos, w1_tacos, True),
                    '预警原因': f"周波动: {w_pct:.1%}", '波动驱动因素': build_driving_factors_text(w_units_diff, w2_gv-w1_gv, w2_price-w1_price, w2_cvr-w1_cvr, w2_sp-w1_sp, w2_tacos-w1_tacos),
                    'w_diff_abs': abs(w_units_diff)
                })
            df_s6_all = pd.DataFrame(s6_records)
            df_s6_top50 = df_s6_all.sort_values(by='w_diff_abs', ascending=False).head(50).drop(columns=['w_diff_abs']).reset_index(drop=True)
            df_s6_top50.insert(0, 'Rank', df_s6_top50.index + 1)
        else:
            df_s6_top50 = pd.DataFrame([{'提示': '历史数据不足14天，周环比隐藏'}])

        # ==================== 🎨 样式渲染引擎 ====================
        def apply_matrix_styles(df):
            def fmt_arrow(v):
                if pd.isna(v): return "0"
                if isinstance(v, (int, float)):
                    if v > 0: return f"▲ +{int(v) if v.is_integer() else round(v,2)}"
                    elif v < 0: return f"▼ {int(v) if v.is_integer() else round(v,2)}"
                    return "0"
                return str(v)
            
            def fmt_arrow_pct(v):
                if pd.isna(v): return "0.0%"
                if isinstance(v, (int, float)):
                    if v > 0: return f"▲ +{round(v*100, 1)}%"
                    elif v < 0: return f"▼ {round(v*100, 1)}%"
                    return "0.0%"
                return str(v)

            fmt_dict = {}
            for c in df.columns:
                if '变化率' in c or 'CVR' in c or 'TACOS' in c: fmt_dict[c] = fmt_arrow_pct
                elif '变化' in c or '趋势' in c: fmt_dict[c] = fmt_arrow
                elif 'D1' in c or 'D2' in c or 'W1' in c or 'W2' in c or '均销' in c or 'Day' in c: 
                    fmt_dict[c] = lambda x: f"{int(x):,}" if isinstance(x, (int,float)) else str(x)
            
            def row_painter(row):
                colors = [''] * len(row)
                for i, col_name in enumerate(row.index):
                    if col_name == '预警层级':
                        val_str = str(row[col_name])
                        if '🔴' in val_str or 'High' in val_str or '暴跌' in val_str: colors[i] = 'background-color: #FFC7CE; color: #9C0006; font-weight: bold'
                        elif '⚠️' in val_str or 'Medium' in val_str: colors[i] = 'background-color: #FFEB9C; color: #9C6500'
                        elif '⚪' in val_str or 'Low' in val_str: colors[i] = 'background-color: #F2F2F2; color: #333333'
                        elif 'ℹ️' in val_str or 'Info' in val_str: colors[i] = 'background-color: #DDEBF7; color: #004E82'
                        continue
                        
                    if '销量' in col_name: colors[i] = 'background-color: #DDEBF7;'
                    elif 'GV' in col_name: colors[i] = 'background-color: #E2EFDA;'
                    elif '价格' in col_name or '单价' in col_name: colors[i] = 'background-color: #FFF2CC;'
                    elif 'CVR' in col_name: colors[i] = 'background-color: #FCE4D6;'
                    elif 'SPSD' in col_name or 'SBDSP' in col_name: colors[i] = 'background-color: #E9D7F3;'
                    elif 'TACOS' in col_name: colors[i] = 'background-color: #EDEDED;'
                    
                    if '波动' in col_name or '变化' in col_name or '趋势' in col_name:
                        v = row[col_name]
                        if isinstance(v, (int, float)) and v != 0:
                            if 'SPSD' in col_name or 'SBDSP' in col_name or 'TACOS' in col_name:
                                colors[i] += 'color: #FF0000; font-weight: bold;' if v > 0 else 'color: #00B050; font-weight: bold;'
                            else:
                                colors[i] += 'color: #00B050; font-weight: bold;' if v > 0 else 'color: #FF0000; font-weight: bold;'
                return colors
            return df.style.apply(row_painter, axis=1).format(fmt_dict)

        styler_s2 = apply_matrix_styles(df_top50_s2)
        styler_s3 = apply_matrix_styles(df_s3_alert)
        styler_s4 = apply_matrix_styles(df_s4_top50)
        styler_s5 = apply_matrix_styles(df_s5_alert)
        styler_s6 = df_s6_top50 if '提示' in df_s6_top50.columns else apply_matrix_styles(df_s6_top50)

        # Dashboard 统计数字
        h_c = len(df_child_master[df_child_master['预警层级'].str.contains('🔴', na=False)])
        m_c = len(df_child_master[df_child_master['预警层级'].str.contains('⚠️', na=False)])
        l_c = len(df_child_master[df_child_master['预警层级'].str.contains('⚪', na=False)])
        i_c = len(df_child_master[df_child_master['预警层级'].str.contains('ℹ️', na=False)])
        hp_c = len(df_s5_alert[df_s5_alert['预警层级'].str.contains('🔴', na=False)])
        mp_c = len(df_s5_alert[df_s5_alert['预警层级'].str.contains('⚠️', na=False)])
        lp_c = len(df_s5_alert[df_s5_alert['预警层级'].str.contains('⚪', na=False)])
        ip_c = len(df_s5_alert[df_s5_alert['预警层级'].str.contains('ℹ️', na=False)])

        summary_table = pd.DataFrame([
            {'预警等级': '🔴 第一层 (High)', '核心判定条件说明': '高销量关键产品日销量大幅突变，平均销量≥10 且 波动绝对值≥15件', '已筛选子ASIN数': f"{h_c} 个", '已筛选父ASIN数': f"{hp_c} 个"},
            {'预警等级': '⚠️ 第二层 (Medium)', '核心判定条件说明': '中等销量产品剧烈震荡波动，3≤平均销量<10 且 销量环比涨跌变化率≥60%', '已筛选子ASIN数': f"{m_c} 个", '已筛选父ASIN数': f"{mp_c} 个"},
            {'预警等级': '⚪ 第三层 (Low)', '核心判定条件说明': '历史活跃单品突然无迹象彻底归零预警，L30D日均销≥3 且 前日销量≥3 且 昨日销量=0', '已筛选子ASIN数': f"{l_c} 个", '已筛选父ASIN数': f"{lp_c} 个"},
            {'预警等级': 'ℹ️ 第四层 (Info)', '核心判定条件说明': '单品断货入仓或被限制后重新起死回生恢复预警，前日销量=0 且 昨日销量快速反弹≥3', '已筛选子ASIN数': f"{i_c} 个", '已筛选父ASIN数': f"{ip_c} 个"}
        ])

        # ==================== 📥 内存打包全套样式 Excel 导出 ====================
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            summary_table.to_excel(writer, sheet_name='预警摘要说明', index=False)
            styler_s2.to_excel(writer, sheet_name='子ASIN_TOP50', index=False)
            styler_s3.to_excel(writer, sheet_name='子ASIN_全波动', index=False)
            styler_s4.to_excel(writer, sheet_name='父ASIN_TOP50', index=False)
            styler_s5.to_excel(writer, sheet_name='父ASIN_全波动', index=False)
            if '提示' not in df_s6_top50.columns:
                styler_s6.to_excel(writer, sheet_name='父ASIN_周波动', index=False)
            else:
                df_s6_top50.to_excel(writer, sheet_name='父ASIN_周波动', index=False)
        
        st.download_button(
            label="📥 一键导出完美多维联动切片 Excel 报表 (.xlsx)",
            data=output.getvalue(),
            file_name=f"VC_POS_Alert_Report_{latest_d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )

        # ==================== 📊 页面 UI Tabs 渲染 ====================
        tabs = st.tabs([
            "📋 Sheet 1: 预警摘要说明",
            "🥇 Sheet 2: 子ASIN-TOP50", 
            "🛒 Sheet 3: 子ASIN-全波动", 
            "🏅 Sheet 4: 父ASIN-TOP50", 
            "📦 Sheet 5: 父ASIN-全波动", 
            "🗓️ Sheet 6: 父ASIN-周波动"
        ])
        
        with tabs[0]:
            st.subheader("📋 Amazon VC POS 销售波动监控仪表盘总览")
            st.table(summary_table)
            
            c_inf1, c_inf2 = st.columns(2)
            with c_inf1:
                st.info("""
                **二、大盘底层数据清洗漏斗规则 (已生效)**
                * 自动剔除 `Retail Status` 为 *Discontinued / Temp Discontinued* 的过时死链接。
                * 自动剔除部门代号 (`Division`) 为 *FUR, LGT, ART, APL, PET, PETB* 的非核心业务家具宠物线。
                * 自动过滤 `OM` 标记为 *discontinued* 的产品。
                """)
                st.warning("""
                **三、Revenue Impact 营收震荡系数级别定义**
                * 计算公式：`销量每日净波动 × 昨日单价`
                * **S级影响**：单日震荡金额绝对值 ≥ $5000 (战略级波动)
                * **A级影响**：$1000 - $5000 (高震荡)
                * **B级影响**：$500 - $1000 (中等异动)
                * **C级影响**：$100 - $500 (低度异动)
                """)
            with c_inf2:
                st.success("""
                **四、CVR 转化率矩阵良性/恶性走势诊断**
                * 🟢 良性：`CVR ↑ + 销量 ↑` ➔ 关键词排名自然破圈，流量高度匹配。
                * 🟡 监控：`CVR ↓ + 销量 ↑` ➔ 处于降价、大促清仓阶段，需严防毛利穿底。
                * 🔴 警戒：`CVR ↓ + 销量 ↓` ➔ 产品转化核心爆雷、或遭遇海量差评，须立即抢修 Listing！
                """)
                st.error("""
                **五、TACOS (总广告开销占销售额比) 毛利警示线**
                * 计算公式：`SPSD广告费 / Total Revenue × 100%`
                * 🟢 优异效率：TACOS < 2%
                * 🟡 正常开销：2% ≤ TACOS < 5%
                * 🔴 亟需调价：TACOS ≥ 5%（广告疯狂烧钱空转，建议立刻降CPC或限流）
                """)

        with tabs[1]: st.dataframe(styler_s2, use_container_width=True, height=550)
        with tabs[2]: st.dataframe(styler_s3, use_container_width=True, height=550)
        with tabs[3]: st.dataframe(styler_s4, use_container_width=True, height=550)
        with tabs[4]: st.dataframe(styler_s5, use_container_width=True, height=550)
        with tabs[5]: 
            if '提示' in df_s6_top50.columns: st.info("历史横向数据天数不足 14 天，周滚动环比自动隐藏。")
            else: st.dataframe(styler_s6, use_container_width=True, height=550)

    except Exception as e:
        st.error(f"💥 发生运算错误：{e}")
