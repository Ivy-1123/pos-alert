import streamlit as st
import pandas as pd
import numpy as np
import io

# --- 网页基础设置 ---
st.set_page_config(page_title="VC POS 波动预警终极版", layout="wide", initial_sidebar_state="expanded")
st.title("🚨 Amazon VC POS 销售波动预警报告系统")
st.markdown("不仅提供全自动多维矩阵分析，更搭载了 **数据缓存引擎** 与 **智能表头寻标算法**，支持侧边栏秒级多维过滤与一键导出。")

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
        return '🔴 High', f'高销量产品大幅突变: 平均销量{avg_sales:.0f}≥10且变化{abs(sales_change):.0f}≥15件'
    if 3 <= avg_sales < 10 and sales_prev > 0:
        change_rate = abs(sales_change) / sales_prev
        if change_rate >= 0.60:
            return '⚠️ Medium', f'中销量产品大幅波动: 平均销量{avg_sales:.1f}在3-10且变化率{change_rate:.1%}≥60%'
    if l30d_avg >= 3 and sales_prev >= 3 and sales_latest == 0:
        return '⚪ Low', f'活跃链接归零预警: L30D≥3且前日{sales_prev:.0f}≥3且昨日归零'
    if sales_prev == 0 and sales_latest >= 3:
        return 'ℹ️ Info', f'归零后恢复预警: 前日归零但昨日恢复至{sales_latest:.0f}≥3'
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


# ==================== 🚀 核心更新：数据读取缓存与智能表头引擎 ====================
@st.cache_data(show_spinner=False)
def load_and_parse_data(file_bytes, file_name):
    if file_name.endswith('.csv'):
        raw_df = pd.read_csv(io.BytesIO(file_bytes), header=None, low_memory=False)
    else:
        raw_df = pd.read_excel(io.BytesIO(file_bytes), header=None)
    
    raw_df.iloc[:, 0] = raw_df.iloc[:, 0].ffill()
    
    date_row = raw_df.iloc[0, :]
    sub_header_row = raw_df.iloc[1, :]
    
    # 1. 动态智能定位前 20 列的基础属性 (防错位引擎)
    meta_headers = [str(x).strip().lower() for x in sub_header_row[:25]]
    idx_map = {
        'parent': 0, 'asin': 1, 'item_no': 2, 'division': 3, 'brand': 4,
        'category': 5, 'subcat': 6, 'pattern': 7, 'color': 8, 'size': 9,
        'om': 11, 'buckets': 12, 'class_code': 13, 'tag': 15, 'status': 18
    }
    
    for i, h in enumerate(meta_headers):
        if 'parent' in h and 'asin' in h: idx_map['parent'] = i
        elif h == 'asin': idx_map['asin'] = i
        elif 'division' in h: idx_map['division'] = i
        elif 'brand' in h: idx_map['brand'] = i
        elif 'category' in h and 'sub' not in h: idx_map['category'] = i
        elif 'subcategory' in h or 'sub category' in h: idx_map['subcat'] = i
        elif 'pattern' in h: idx_map['pattern'] = i
        elif 'color' in h: idx_map['color'] = i
        elif 'size' in h: idx_map['size'] = i
        elif h == 'om': idx_map['om'] = i
        elif 'status' in h: idx_map['status'] = i
    
    # 2. 定位动态日期及核心财务列
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
    
    # 3. 数据漏斗清洗
    cleaned_rows = []
    for idx, row in raw_df.iloc[2:].iterrows():
        parent_asin = str(row.iloc[idx_map['parent']]).strip()
        asin = str(row.iloc[idx_map['asin']]).strip()
        division = str(row.iloc[idx_map['division']]).strip()
        om = str(row.iloc[idx_map['om']]).strip()
        retail_status = str(row.iloc[idx_map['status']]).strip().lower()
        
        if parent_asin.lower() in ['total', '总计', 'nan', '']: continue
        if asin.lower() in ['total', '总计', 'nan', '', 'asin']: continue
        if retail_status in ['discontinued', 'temp discontinued']: continue
        if division in ['FUR', 'LGT', 'ART', 'APL', 'PET', 'PETB']: continue
        if om.lower() == 'discontinued': continue
        cleaned_rows.append(row)
        
    if not cleaned_rows:
        return None, None, None, "⚠️ 过滤后未留下任何有效明细！"

    # 4. 构建全数据源缓存池
    child_list = []
    for row in cleaned_rows:
        # 使用动态索引精准抓取
        parent_asin = str(row.iloc[idx_map['parent']]).strip()
        asin = str(row.iloc[idx_map['asin']]).strip()
        item_no = str(row.iloc[idx_map['item_no']]).strip()
        division = str(row.iloc[idx_map['division']]).strip()
        brand = str(row.iloc[idx_map['brand']]).strip()
        category = str(row.iloc[idx_map['category']]).strip()
        subcat = str(row.iloc[idx_map['subcat']]).strip()
        pattern = str(row.iloc[idx_map['pattern']]).strip()
        color = str(row.iloc[idx_map['color']]).strip()
        size = str(row.iloc[idx_map['size']]).strip()
        om = str(row.iloc[idx_map['om']]).strip()
        buckets = str(row.iloc[idx_map['buckets']]).strip()
        class_code = str(row.iloc[idx_map['class_code']]).strip()
        prod_tag = str(row.iloc[idx_map['tag']]).strip()
        retail_status = str(row.iloc[idx_map['status']]).strip()
        
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
            'Parent ASIN': parent_asin, 'ASIN': asin, 'ItemNo': item_no, 'Division': division, 'Brand': brand,
            'Category': category, 'Subcategory': subcat, 'Pattern': pattern, 'Color': color, 'Size': size,
            'OM': om, 'BucketsList': buckets, 'ClassificationCode': class_code, 'ProductTag': prod_tag, 'Retail Status': retail_status,
            'L30D销量均值': l30d_avg, 'units_p': u_p, 'units_l': u_l, 'gv_p': gv_p, 'gv_l': gv_l, 'price_p': pr_p, 'price_l': pr_l,
            'cvr_p': cv_p, 'cvr_l': cv_l, 'spsd_p': sp_p, 'spsd_l': sp_l, 'sbdsp_p': sb_p, 'sbdsp_l': sb_l, 'tacos_p': tc_p, 'tacos_l': tc_l,
            'Revenue_Impact': fmt_impact, '影响级别': get_revenue_impact_level(rev_impact), '预警层级': tier if tier else '无预警', '预警原因': reason, '波动驱动因素': driving,
            'raw_row_data': row, 'rev_p': rev_p, 'rev_l': u_l * pr_l
        })
        
    df_child_master_cached = pd.DataFrame(child_list)
    return df_child_master_cached, sorted_dates, date_blocks, None
# ==============================================================================


# --- 网页上传组件 ---
uploaded_file = st.file_uploader("📂 请上传原始 VC ASIN 复合数据表 (支持 xlsx 或 csv)", type=['xlsx', 'csv'])

if uploaded_file is not None:
    with st.spinner('🔥 正在加载基础数据 (首次需数秒，后续筛选秒开)...'):
        try:
            df_child_cached, sorted_dates, date_blocks, err_msg = load_and_parse_data(uploaded_file.getvalue(), uploaded_file.name)
            
            if err_msg:
                st.error(err_msg)
                st.stop()
                
            latest_d, prev_d = sorted_dates[0], sorted_dates[1]
            df_child_master = df_child_cached.copy()

            # ==================== 🎛️ 侧边栏筛选引擎 ====================
            st.sidebar.header("🔍 数据多维侧边栏过滤")
            
            om_options = sorted([str(x) for x in df_child_master['OM'].unique() if pd.notna(x) and str(x).strip() != ''])
            pattern_options = sorted([str(x) for x in df_child_master['Pattern'].unique() if pd.notna(x) and str(x).strip() != ''])
            
            selected_oms = st.sidebar.multiselect("👨‍💼 筛选负责团队 (OM)", options=om_options, default=None, placeholder="选择 OM (支持多选)...")
            selected_patterns = st.sidebar.multiselect("🎨 筛选产品款式 (Pattern)", options=pattern_options, default=None, placeholder="选择款式 (支持多选)...")
            
            if selected_oms:
                df_child_master = df_child_master[df_child_master['OM'].astype(str).isin(selected_oms)]
            if selected_patterns:
                df_child_master = df_child_master[df_child_master['Pattern'].astype(str).isin(selected_patterns)]
            
            if df_child_master.empty:
                st.warning("⚠️ 没有匹配到任何数据，请在左侧栏调整您的多选项。")
                st.stop()
            # ==========================================================

            s2_s3_rows = []
            for idx, r in df_child_master.iterrows():
                s2_s3_rows.append({
                    'Parent ASIN': r['Parent ASIN'], 'ASIN': r['ASIN'], 'ItemNo': r['ItemNo'], 'Division': r['Division'], 'Brand': r['Brand'],
                    'OM': r['OM'], 'Pattern': r['Pattern'], 'ProductTag': r['ProductTag'], 'Retail Status': r['Retail Status'], 'L30D销量均值': int(r['L30D销量均值']),
                    '销量_Day1': int(r['units_p']), '销量_Day2': int(r['units_l']), '销量变化': int(r['units_l'] - r['units_p']), '销量变化率': (r['units_l'] - r['units_p'])/r['units_p'] if r['units_p'] > 0 else 0.0,
                    'GV_Day1': int(r['gv_p']), 'GV_Day2': int(r['gv_l']), 'GV变化': int(r['gv_l'] - r['gv_p']), 'GV变化率': (r['gv_l'] - r['gv_p'])/r['gv_p'] if r['gv_p'] > 0 else 0.0,
                    '价格_Day1': r['price_p'], '价格_Day2': r['price_l'], '价格变化': r['price_l'] - r['price_p'], '价格变化率': (r['price_l'] - r['price_p'])/r['price_p'] if r['price_p'] > 0 else 0.0,
                    'CVR_Day1': r['cvr_p'], 'CVR_Day2': r['cvr_l'], 'CVR变化': r['cvr_l'] - r['cvr_p'], 'CVR变化率': (r['cvr_l'] - r['cvr_p'])/r['cvr_p'] if r['cvr_p'] > 0 else 0.0,
                    'SPSD_Day1': int(r['spsd_p']), 'SPSD_Day2': int(r['spsd_l']), 'SPSD变化': int(r['spsd_l'] - r['spsd_p']), 'SPSD变化率': (r['spsd_l'] - r['spsd_p'])/r['spsd_p'] if r['spsd_p'] > 0 else 0.0,
                    'SBDSP_Day1': int(r['sbdsp_p']), 'SBDSP_Day2': int(r['sbdsp_l']), 'SBDSP变化': int(r['sbdsp_l'] - r['sbdsp_p']), 'SBDSP变化率': (r['sbdsp_l'] - r['sbdsp_p'])/r['sbdsp_p'] if r['sbdsp_p'] > 0 else 0.0,
                    'TACOS_Day1': r['tacos_p'], 'TACOS_Day2': r['tacos_l'], 'TACOS变化': r['tacos_l'] - r['tacos_p'], 'TACOS变化率': (r['tacos_l'] - r['tacos_p'])/r['tacos_p'] if r['tacos_p'] > 0 else 0.0,
                    'Revenue_Impact': r['Revenue_Impact'], '影响级别': r['影响级别'], '预警层级': r['预警层级'], '预警原因': r['预警原因'], '波动驱动因素': r['波动驱动因素'],
                    'u_diff': abs(r['units_l'] - r['units_p'])
                })
            df_s3_all = pd.DataFrame(s2_s3_rows)
            df_s3_alert = df_s3_all[df_s3_all['预警层级'] != '无预警'].sort_values(by='u_diff', ascending=False).drop(columns=['u_diff']).reset_index(drop=True)
            df_s3_alert.insert(0, 'Rank', df_s3_alert.index + 1)
            
            df_top50_s2 = df_s3_alert.head(50).copy()
            
            parent_group = df_child_master.groupby('Parent ASIN').agg({
                'ASIN': 'nunique', 'Division': 'first', 'Brand': 'first', 'Pattern': 'first', 'OM': 'first', 'ProductTag': 'first', 'Retail Status': 'first',
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
                    'Parent ASIN': row['Parent ASIN'], 'ASIN count': int(row['ASIN']), 'Division': row['Division'], 'Brand': row['Brand'],
                    'OM': row['OM'], 'Pattern': row['Pattern'], 'ProductTag': row['ProductTag'], 'Retail Status': row['Retail Status'], 'L30D销量均值': int(row['L30D销量均值']),
                    '销量_Day1': int(u_p), '销量_Day2': int(u_l), '销量变化': int(p_change), '销量变化率': p_change/u_p if u_p > 0 else 0.0, 
                    'GV_Day1': int(gv_p), 'GV_Day2': int(gv_l), 'GV变化': int(gv_l - gv_p), 'GV变化率': (gv_l - gv_p)/gv_p if gv_p > 0 else 0.0, 
                    '价格_Day1': pr_p, '价格_Day2': pr_l, '价格变化': pr_l - pr_p, '价格变化率': (pr_l - pr_p)/pr_p if pr_p > 0 else 0.0, 
                    'CVR_Day1': cv_p, 'CVR_Day2': cv_l, 'CVR变化': cv_l - cv_p, 'CVR变化率': (cv_l - cv_p)/cv_p if cv_p > 0 else 0.0, 
                    'SPSD_Day1': int(sp_p), 'SPSD_Day2': int(sp_l), 'SPSD变化': int(sp_l - sp_p), 'SPSD变化率': (sp_l - sp_p)/sp_p if sp_p > 0 else 0.0, 
                    'SBDSP_Day1': int(sb_p), 'SBDSP_Day2': int(sb_l), 'SBDSP变化': int(sb_l - sb_p), 'SBDSP变化率': (sb_l - sb_p)/sb_p if sb_p > 0 else 0.0, 
                    'TACOS_Day1': tc_p, 'TACOS_Day2': tc_l, 'TACOS变化': tc_l - tc_p, 'TACOS变化率': (tc_l - tc_p)/tc_p if tc_p > 0 else 0.0, 
                    'Revenue_Impact': fmt_p_impact, '影响级别': get_revenue_impact_level(p_impact), '预警层级': p_tier if p_tier else '无预警', '预警原因': p_reason, 
                    '波动驱动因素': build_driving_factors_text(p_change, gv_l - gv_p, pr_l - pr_p, cv_l - cv_p, sp_l - sp_p, tc_l - tc_p),
                    'p_u_diff': abs(p_change)
                })
            df_s5_all = pd.DataFrame(parent_list)
            df_s5_alert = df_s5_all[df_s5_all['预警层级'] != '无预警'].sort_values(by='p_u_diff', ascending=False).drop(columns=['p_u_diff']).reset_index(drop=True)
            df_s5_alert.insert(0, 'Rank', df_s5_alert.index + 1)
            
            df_s4_top50 = df_s5_alert.head(50).copy()

            h_c = len(df_child_master[df_child_master['预警层级'].str.contains('🔴', na=False)])
            m_c = len(df_child_master[df_child_master['预警层级'].str.contains('⚠️', na=False)])
            l_c = len(df_child_master[df_child_master['预警层级'].str.contains('⚪', na=False)])
            i_c = len(df_child_master[df_child_master['预警层级'].str.contains('ℹ️', na=False)])
            
            hp_c = len(df_s5_alert[df_s5_alert['预警层级'].str.contains('🔴', na=False)])
            mp_c = len(df_s5_alert[df_s5_alert['预警层级'].str.contains('⚠️', na=False)])
            lp_c = len(df_s5_alert[df_s5_alert['预警层级'].str.contains('⚪', na=False)])
            ip_c = len(df_s5_alert[df_s5_alert['预警层级'].str.contains('ℹ️', na=False)])

            s6_records = []
            if len(sorted_dates) >= 14:
                w2_days, w1_days = sorted_dates[:7], sorted_dates[7:14]  
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
                    
                    s6_records.append({
                        'Parent ASIN': p_asin, 'ASIN count': int(p_row['ASIN']), 'Division': p_row['Division'], 'Brand': p_row['Brand'], 'OM': p_row['OM'], 'Pattern': p_row['Pattern'],
                        '销量_W1': int(w1_units), '销量_W2': int(w2_units), '销量变化': int(w_units_diff), '销量变化率': w_pct,
                        'GV_W1': int(w1_gv), 'GV_W2': int(w2_gv), 'GV变化': int(w2_gv - w1_gv), 'GV变化率': (w2_gv - w1_gv)/w1_gv if w1_gv > 0 else 0.0,
                        '价格_W1': w1_price, '价格_W2': w2_price, '价格变化': w2_price - w1_price, '价格变化率': (w2_price - w1_price)/w1_price if w1_price > 0 else 0.0,
                        'SPSD_W1': int(w1_sp), 'SPSD_W2': int(w2_sp), 'SPSD变化': int(w2_sp - w1_sp), 'SPSD变化率': (w2_sp - w1_sp)/w1_sp if w1_sp > 0 else 0.0,
                        'CVR_W1': w1_cvr, 'CVR_W2': w2_cvr, 'CVR变化': w2_cvr - w1_cvr, 'CVR变化率': (w2_cvr - w1_cvr)/w1_cvr if w1_cvr > 0 else 0.0,
                        'TACOS_W1': w1_tacos, 'TACOS_W2': w2_tacos, 'TACOS变化': w2_tacos - w1_tacos, 'TACOS变化率': (w2_tacos - w1_tacos)/w1_tacos if w1_tacos > 0 else 0.0,
                        '预警层级': w_alert, 'w_diff_abs': abs(w_units_diff)
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
                    elif 'Day' in c or 'W1' in c or 'W2' in c or '均销' in c: 
                        fmt_dict[c] = lambda x: f"{int(x):,}" if isinstance(x, (int,float)) else str(x)
                
                def row_painter(row):
                    colors = [''] * len(row)
                    for i, col_name in enumerate(row.index):
                        if col_name == '预警层级':
                            val_str = str(row[col_name])
                            if '🔴' in val_str or 'High' in val_str or '暴跌' in val_str:
                                colors[i] = 'background-color: #FFC7CE; color: #9C0006; font-weight: bold'
                            elif '⚠️' in val_str or 'Medium' in val_str:
                                colors[i] = 'background-color: #FFEB9C; color: #9C6500'
                            elif '⚪' in val_str or 'Low' in val_str:
                                colors[i] = 'background-color: #F2F2F2; color: #333333'
                            elif 'ℹ️' in val_str or 'Info' in val_str:
                                colors[i] = 'background-color: #DDEBF7; color: #004E82'
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

            summary_table = pd.DataFrame([
                {'预警等级': '🔴 第一层 (High)', '核心判定条件说明': '高销量关键产品日销量大幅突变，平均销量≥10 且 波动绝对值≥15件', '已筛选子ASIN数': f"{h_c} 个", '已筛选父ASIN数': f"{hp_c} 个"},
                {'预警等级': '⚠️ 第二层 (Medium)', '核心判定条件说明': '中等销量产品剧烈震荡波动，3≤平均销量<10 且 销量环比涨跌变化率≥60%', '已筛选子ASIN数': f"{m_c} 个", '已筛选父ASIN数': f"{mp_c} 个"},
                {'预警等级': '⚪ 第三层 (Low)', '核心判定条件说明': '历史活跃单品突然无迹象彻底归零预警，L30D日均销≥3 且 前日销量≥3 且 昨日销量=0', '已筛选子ASIN数': f"{l_c} 个", '已筛选父ASIN数': f"{lp_c} 个"},
                {'预警等级': 'ℹ️ 第四层 (Info)', '核心判定条件说明': '单品断货入仓或被限制后重新起死回生恢复预警，前日销量=0 且 昨日销量快速反弹≥3', '已筛选子ASIN数': f"{i_c} 个", '已筛选父ASIN数': f"{ip_c} 个"}
            ])

            # ==================== 📥 Excel 构建 ====================
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
            
            excel_data = output.getvalue()
            
            st.success(f"✅ 多维联动过滤已就绪！缓存读取耗时不到 0.1 秒。")
            st.download_button(
                label="📥 点击这里一键导出带红绿样式的全套 Excel 报表 (.xlsx)",
                data=excel_data,
                file_name=f"VC_多维联动切割报告_{latest_d}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )

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
