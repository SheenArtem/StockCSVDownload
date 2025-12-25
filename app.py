import streamlit as st
import yfinance as yf
import pandas as pd
import io
import zipfile
from datetime import datetime
from FinMind.data import DataLoader

# 設定網頁標題
st.set_page_config(page_title="全方位股票籌碼下載器", page_icon="📦")
st.title('📦 台股/美股 籌碼與數據下載器')
st.markdown("### 批次分析：一次輸入多檔代號，下載包含「法人、資券、大戶」的 CSV。")

# ==========================================
#  區塊 1: 股票批次下載 (原有功能 - 日線+籌碼)
# ==========================================
st.subheader("1. 股票批次下載 (日線 + 籌碼)")

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
if st.button('🚀 開始批次抓取並打包 (Stocks)'):
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
                status_text.text(f"正在下載 ({i+1}/{len(tickers)}): {ticker_symbol} ...")
                progress_bar.progress((i + 1) / len(tickers))
                
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
                        if 'Date' in df.columns:
                            df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)

                        # 🛡️ 安全初始化：先建立空欄位 (防呆)
                        chip_cols = [
                            'Foreign_Net', 'Trust_Net', 'Dealer_Net', # 三大法人
                            'Margin_Balance', 'Short_Balance',        # 融資券
                            'Big_Hands_Pct', 'Small_Hands_Pct',       # 集保分佈
                            'Chip_Spread'                             # 籌碼差
                        ]
                        for c in chip_cols:
                            df[c] = 0.0

                        # 🇹🇼 台股專屬：抓取 FinMind 籌碼
                        if is_tw_stock:
                            try:
                                start_date = (datetime.now() - pd.DateOffset(years=5)).strftime('%Y-%m-%d')
                                
                                # A. 三大法人
                                df_inst = fm.taiwan_stock_institutional_investors(stock_id=stock_id_only, start_date=start_date)
                                if not df_inst.empty:
                                    df_inst['date'] = pd.to_datetime(df_inst['date'])
                                    pivot = df_inst.pivot_table(index='date', columns='name', values=['buy', 'sell'], aggfunc='sum').fillna(0)
                                    
                                    def get_net(name):
                                        if name in pivot['buy'] and name in pivot['sell']:
                                            return pivot['buy'][name] - pivot['sell'][name]
                                        return 0
                                    
                                    temp_df = pd.DataFrame(index=pivot.index)
                                    temp_df['Foreign_Net'] = get_net('Foreign_Investor')
                                    temp_df['Trust_Net'] = get_net('Investment_Trust')
                                    temp_df['Dealer_Net'] = get_net('Dealer_Self_Analysis')
                                    
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

                                # C. 集保股權分散
                                df_holding = fm.taiwan_stock_holding_shares_per(stock_id=stock_id_only, start_date=start_date)
                                if not df_holding.empty:
                                    df_holding['date'] = pd.to_datetime(df_holding['date'])
                                    df_holding['percent'] = pd.to_numeric(df_holding['percent'], errors='coerce')
                                    df_holding['HoldingSharesLevel'] = pd.to_numeric(df_holding['HoldingSharesLevel'], errors='coerce')
                                    
                                    grp = df_holding.groupby('date')
                                    big = grp.apply(lambda x: x[x['HoldingSharesLevel'] >= 12]['percent'].sum())
                                    small = grp.apply(lambda x: x[x['HoldingSharesLevel'] <= 3]['percent'].sum())
                                    
                                    temp_hold = pd.DataFrame({'Big_Hands_Pct': big, 'Small_Hands_Pct': small})
                                    temp_hold['Chip_Spread'] = temp_hold['Big_Hands_Pct'] - temp_hold['Small_Hands_Pct']
                                    
                                    df.set_index('Date', inplace=True)
                                    df = pd.merge(df, temp_hold, left_index=True, right_index=True, how='left', suffixes=('', '_new'))
                                    for col in ['Big_Hands_Pct', 'Small_Hands_Pct', 'Chip_Spread']:
                                        if f'{col}_new' in df.columns:
                                            df[col] = df[f'{col}_new'].combine_first(df[col])
                                            df.drop(columns=[f'{col}_new'], inplace=True)
                                    df.reset_index(inplace=True)
                                    df[['Big_Hands_Pct', 'Small_Hands_Pct', 'Chip_Spread']] = df[['Big_Hands_Pct', 'Small_Hands_Pct', 'Chip_Spread']].ffill()

                            except Exception as e:
                                print(f"FinMind Warning: {e}")
                                pass

                        # 🧮 通用指標
                        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').fillna(0)
                        df['Main_Force_Net'] = df['Foreign_Net'] + df['Trust_Net'] + df['Dealer_Net']
                        df['Concentration_5'] = (df['Main_Force_Net'].rolling(5).sum() / (df['Volume'].rolling(5).sum() + 1e-9) * 100).round(2)
                        df['Concentration_20'] = (df['Main_Force_Net'].rolling(20).sum() / (df['Volume'].rolling(20).sum() + 1e-9) * 100).round(2)
                        
                        close_diff = df['Close'].diff()
                        df['Raw_Force'] = close_diff * df['Volume']
                        df['EFI_13'] = df['Raw_Force'].ewm(span=13, adjust=False).mean()

                        # 存檔
                        df.fillna(0, inplace=True)
                        csv_data = df.to_csv(index=False).encode('utf-8-sig')
                        zf.writestr(f"{real_ticker}.csv", csv_data)
                        success_count += 1
                        
                    else:
                        st.error(f"❌ {real_ticker} 查無資料")
                except Exception as e:
                    st.error(f"❌ {real_ticker} 下載失敗: {e}")

        progress_bar.progress(100)
        status_text.text(f"處理完成！成功打包 {success_count} 檔股票。")
        
        if success_count > 0:
            zip_buffer.seek(0)
            filename = f"Stock_Batch_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
            st.download_button(
                label=f"📥 下載 ZIP 壓縮檔 ({success_count} 檔)",
                data=zip_buffer,
                file_name=filename,
                mime="application/zip"
            )

# ==========================================
#  區塊 2: 台指期專屬下載 (FinMind 版 - 最穩)
# ==========================================
st.markdown("---")
st.subheader("2. ⏱️ 台指期 (TX) 小時 K 下載 - FinMind 來源")
st.info("💡 使用 FinMind 台灣在地數據源，解決 Yahoo Finance 常抓不到資料的問題。程式會自動將「分鐘線」合成「小時線」。")

# 讓使用者選擇開始日期
start_date_input = st.date_input("開始日期", value=pd.to_datetime("2023-01-01"))

if st.button("🚀 下載台指期 (TX) 小時 K"):
    
    with st.spinner('正在從 FinMind 下載台指期分鐘資料並運算中 (需時較久，請稍候)...'):
        try:
            # 1. 初始化 DataLoader (使用您的 app.py 已有的 import)
            fm = DataLoader()
            
            # 2. 下載台指期 (TX) 的 1 分鐘資料
            # FinMind 的台指期代號通常是 'TX'
            start_str = start_date_input.strftime('%Y-%m-%d')
            df_min = fm.taiwan_futures_minute(
                futures_id='TX',
                start_date=start_str
            )
            
            if not df_min.empty:
                # 3. 數據清洗與重採樣 (Resample 1min -> 1h)
                # 確保 date 是 datetime 格式並設為索引
                df_min['date'] = pd.to_datetime(df_min['date'])
                df_min.set_index('date', inplace=True)
                
                # 定義合併規則 (OHLCV)
                # Open取第一筆, High取最大, Low取最小, Close取最後, Volume取加總
                logic = {
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }
                
                # 執行重採樣 (1H = 1小時)
                # label='left' 代表 09:00-10:00 的 K 線標示為 09:00
                df_hour = df_min.resample('1H', label='left', closed='left').agg(logic)
                
                # 移除沒有成交量的時段 (例如夜盤休息時間或假日)
                df_hour = df_hour[df_hour['volume'] > 0].dropna()
                df_hour.reset_index(inplace=True)
                
                # 欄位重新命名以符合我的分析格式 (首字大寫)
                df_hour.rename(columns={
                    'date': 'Datetime', 
                    'open': 'Open', 
                    'high': 'High', 
                    'low': 'Low', 
                    'close': 'Close', 
                    'volume': 'Volume'
                }, inplace=True)

                # 4. 產生 CSV
                csv_futures = df_hour.to_csv(index=False).encode('utf-8-sig')
                
                st.success(f"✅ 下載成功！資料來源：FinMind | 區間：{df_hour['Datetime'].min()} 至 {df_hour['Datetime'].max()}")
                
                filename_futures = f"TX_Hourly_FinMind_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
                st.download_button(
                    label=f"📥 點擊下載 {filename_futures}",
                    data=csv_futures,
                    file_name=filename_futures,
                    mime="text/csv"
                )
            else:
                st.error("❌ 下載失敗：FinMind 回傳空資料，請檢查網路或縮短日期範圍。")
                
        except Exception as e:
            st.error(f"❌ 發生錯誤: {e}")
