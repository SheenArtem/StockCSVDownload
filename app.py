import streamlit as st
import yfinance as yf
import pandas as pd
import io
import zipfile
from datetime import datetime
from FinMind.data import DataLoader

# 設定網頁標題
st.set_page_config(page_title="大量股票數據批次下載器", page_icon="📦")
st.title('📦 台股/美股 批次資料下載器')
st.markdown("### 適合大量分析：一次輸入多檔代號，下載 ZIP 包，直接丟給 Gemini。")

# 1. 輸入區塊
col1, col2 = st.columns([3, 1])
with col1:
    # 支援換行或逗號分隔
    raw_tickers = st.text_area(
        "輸入股票代號 (用逗號或換行分隔)", 
        value="2330, 2317, 2454, NVDA, TSLA", 
        height=150
    )
with col2:
    period = st.selectbox("時間長度", ["1y", "3y", "5y", "10y"], index=0)
    st.markdown("---")
    st.caption("自動補全 .TW")

# 按鈕觸發
if st.button('🚀 開始批次抓取並打包'):
    tickers = [t.strip().upper() for t in raw_tickers.replace('\n', ',').split(',') if t.strip()]
    
    if not tickers:
        st.warning("請至少輸入一檔股票代號。")
    else:
        zip_buffer = io.BytesIO()
        progress_bar = st.progress(0)
        status_text = st.empty()
        success_count = 0
        
        # 初始化 FinMind Loader
        fm = DataLoader()
        
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, ticker_symbol in enumerate(tickers):
                # ... (進度條 code 不變)
                
                # 判斷是否為台股 (全數字為台股)
                is_tw_stock = ticker_symbol.isdigit()
                
                real_ticker = ticker_symbol
                stock_id_only = ticker_symbol
                
                if is_tw_stock:
                    real_ticker = f"{ticker_symbol}.TW"
                
                try:
                    # 1. 下載股價 (YFinance - 台美股通用)
                    df = yf.download(real_ticker, period=period, interval="1d", progress=False)
                    
                    if not df.empty:
                        # 基礎清洗
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(0)
                        df.reset_index(inplace=True)
                        df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)

                        # ==========================================
                        #  🛡️ 安全初始化：先建立空欄位 (防呆關鍵)
                        # ==========================================
                        # 無論台美股，先預設這些籌碼欄位為 0
                        # 這樣後面的公式運算就不會因為找不到欄位而當機
                        chip_cols = [
                            'Foreign_Net', 'Trust_Net', 'Dealer_Net', # 三大法人
                            'Margin_Balance', 'Short_Balance',        # 融資券
                            'Big_Hands_Pct', 'Small_Hands_Pct',       # 集保分佈
                            'Chip_Spread'                             # 籌碼差
                        ]
                        for c in chip_cols:
                            df[c] = 0.0

                        # ==========================================
                        #  🇹🇼 台股專屬：抓取 FinMind 籌碼
                        # ==========================================
                        if is_tw_stock:
                            try:
                                # 設定 FinMind 起始日
                                start_date = (datetime.now() - pd.DateOffset(years=5)).strftime('%Y-%m-%d')
                                
                                # A. 三大法人
                                df_inst = fm.taiwan_stock_institutional_investors(stock_id=stock_id_only, start_date=start_date)
                                if not df_inst.empty:
                                    df_inst['date'] = pd.to_datetime(df_inst['date'])
                                    pivot = df_inst.pivot_table(index='date', columns='name', values=['buy', 'sell'], aggfunc='sum').fillna(0)
                                    
                                    # 寫入 DataFrame (使用 update 或 merge)
                                    # 這裡為了簡單，先算出暫存 Series 再映射
                                    # 注意：需處理可能的 Key Error (若某法人當天沒交易)
                                    def get_net(name):
                                        if name in pivot['buy'] and name in pivot['sell']:
                                            return pivot['buy'][name] - pivot['sell'][name]
                                        return 0
                                    
                                    # 建立暫存 DF 來合併，避免 Index 問題
                                    temp_df = pd.DataFrame(index=pivot.index)
                                    temp_df['Foreign_Net'] = get_net('Foreign_Investor')
                                    temp_df['Trust_Net'] = get_net('Investment_Trust')
                                    temp_df['Dealer_Net'] = get_net('Dealer_Self_Analysis') # 自營商(自行)
                                    
                                    # 合併進主表 (update 僅更新有值的)
                                    df.set_index('Date', inplace=True)
                                    df.update(temp_df)
                                    df.reset_index(inplace=True)

                                # B. 融資融券
                                df_margin = fm.taiwan_stock_margin_purchase_short_sale(stock_id=stock_id_only, start_date=start_date)
                                if not df_margin.empty:
                                    df_margin['date'] = pd.to_datetime(df_margin['date'])
                                    df_margin.set_index('date', inplace=True)
                                    df_margin.rename(columns={'MarginPurchaseTodayBalance': 'Margin_Balance', 'ShortSaleTodayBalance': 'Short_Balance'}, inplace=True)
                                    
                                    df.set_index('Date', inplace=True)
                                    df.update(df_margin[['Margin_Balance', 'Short_Balance']])
                                    df.reset_index(inplace=True)

                                # C. 集保股權分散 (週資料)
                                df_holding = fm.taiwan_stock_holding_shares_per(stock_id=stock_id_only, start_date=start_date)
                                if not df_holding.empty:
                                    df_holding['date'] = pd.to_datetime(df_holding['date'])
                                    df_holding['percent'] = pd.to_numeric(df_holding['percent'], errors='coerce')
                                    df_holding['HoldingSharesLevel'] = pd.to_numeric(df_holding['HoldingSharesLevel'], errors='coerce')
                                    
                                    # 大戶 (>400張, Level>=12) vs 散戶 (<5張, Level<=3)
                                    grp = df_holding.groupby('date')
                                    big = grp.apply(lambda x: x[x['HoldingSharesLevel'] >= 12]['percent'].sum())
                                    small = grp.apply(lambda x: x[x['HoldingSharesLevel'] <= 3]['percent'].sum())
                                    
                                    temp_hold = pd.DataFrame({'Big_Hands_Pct': big, 'Small_Hands_Pct': small})
                                    temp_hold['Chip_Spread'] = temp_hold['Big_Hands_Pct'] - temp_hold['Small_Hands_Pct']
                                    
                                    # 合併並填補 (週 -> 日)
                                    df.set_index('Date', inplace=True)
                                    # 先 merge 會有空值，再 ffill
                                    df = pd.merge(df, temp_hold, left_index=True, right_index=True, how='left', suffixes=('', '_new'))
                                    # 更新欄位
                                    for col in ['Big_Hands_Pct', 'Small_Hands_Pct', 'Chip_Spread']:
                                        if f'{col}_new' in df.columns:
                                            df[col] = df[f'{col}_new'].combine_first(df[col]) # 優先用新資料
                                            df.drop(columns=[f'{col}_new'], inplace=True)
                                    
                                    df.reset_index(inplace=True)
                                    # 針對集保數據做 ffill (讓週五數據延續到下週四)
                                    df[['Big_Hands_Pct', 'Small_Hands_Pct', 'Chip_Spread']] = df[['Big_Hands_Pct', 'Small_Hands_Pct', 'Chip_Spread']].ffill()

                            except Exception as e:
                                print(f"FinMind 錯誤 (不影響主流程): {e}")
                                # 出錯了也沒關係，因為我們最上面已經「安全初始化」為 0 了
                                pass

                        # ==========================================
                        #  🧮 通用計算：主力指標 & EFI (台美股皆可算)
                        # ==========================================
                        
                        # 1. 確保 Volume 是數值
                        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').fillna(0)
                        
                        # 2. 計算主力總買賣超 (美股這邊會是 0+0+0=0，不會報錯)
                        df['Main_Force_Net'] = df['Foreign_Net'] + df['Trust_Net'] + df['Dealer_Net']

                        # 3. 計算 5日/20日 集中度
                        # 分母加 1e-9 避免除以零
                        df['Concentration_5'] = (df['Main_Force_Net'].rolling(5).sum() / (df['Volume'].rolling(5).sum() + 1e-9) * 100).round(2)
                        df['Concentration_20'] = (df['Main_Force_Net'].rolling(20).sum() / (df['Volume'].rolling(20).sum() + 1e-9) * 100).round(2)

                        # 4. 埃爾德強力指標 (EFI) - 美股也可以用！
                        close_diff = df['Close'].diff()
                        df['Raw_Force'] = close_diff * df['Volume']
                        df['EFI_13'] = df['Raw_Force'].ewm(span=13, adjust=False).mean()

                        # ==========================================
                        #  💾 存檔
                        # ==========================================
                        df.fillna(0, inplace=True)
                        csv_data = df.to_csv(index=False).encode('utf-8-sig')
                        zf.writestr(f"{real_ticker}.csv", csv_data)
                        success_count += 1
                        
                    else:
                        st.error(f"❌ {real_ticker} 查無資料")
                except Exception as e:
                    st.error(f"❌ {real_ticker} 下載失敗: {e}"

        # 下載完成
        progress_bar.progress(100)
        status_text.text(f"處理完成！成功打包 {success_count} 檔股票。")
        
        if success_count > 0:
            # 讓 ZIP 指標回到開頭
            zip_buffer.seek(0)
            
            # 下載按鈕
            filename = f"Stock_Batch_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
            st.download_button(
                label=f"📥 下載 ZIP 壓縮檔 ({success_count} 檔)",
                data=zip_buffer,
                file_name=filename,
                mime="application/zip"
            )
