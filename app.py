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
                status_text.text(f"正在下載 ({i+1}/{len(tickers)}): {ticker_symbol} ...")
                progress_bar.progress((i + 1) / len(tickers))
                
                # 處理代號
                real_ticker = ticker_symbol
                stock_id_only = ticker_symbol # 用於 FinMind (只要數字)
                
                if ticker_symbol.isdigit():
                    real_ticker = f"{ticker_symbol}.TW"
                    stock_id_only = ticker_symbol
                else:
                    # 美股無法抓 FinMind 籌碼，僅台股適用
                    pass

                try:
                    # 1. 下載股價 (YFinance)
                    df = yf.download(real_ticker, period=period, interval="1d", progress=False)
                    
                    if not df.empty:
                        # 清洗 YF 格式
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(0)
                        df.reset_index(inplace=True)
                        # 確保 Date 是 datetime 格式且不含時區 (以便合併)
                        df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)

                        # 2. 下載籌碼 (FinMind) - 僅限台股數字代號
                        if ticker_symbol.isdigit():
                            try:
                                # 設定起始日期 (配合 YF 的 period，這裡簡單抓 5 年以免不夠)
                                start_date = (datetime.now() - pd.DateOffset(years=5)).strftime('%Y-%m-%d')
                                
                                # A. 下載三大法人
                                df_inst = fm.taiwan_stock_institutional_investors(
                                    stock_id=stock_id_only, start_date=start_date
                                )
                                if not df_inst.empty:
                                    # 整理欄位：將 date 轉為 datetime，並 pivot 轉成寬表格
                                    df_inst['date'] = pd.to_datetime(df_inst['date'])
                                    # 加總三大法人買賣超 (Foreign_Investor, Investment_Trust, Dealer)
                                    # 這裡簡化：直接保留原始格式或 pivot
                                    # 為了方便，我們計算「三大法人合計」與「外資」、「投信」
                                    df_inst_pivot = df_inst.pivot_table(
                                        index='date', 
                                        columns='name', 
                                        values=['buy', 'sell'], 
                                        aggfunc='sum'
                                    ).fillna(0)
                                    
                                    # 算出淨買賣超 (Buy - Sell)
                                    df_net = pd.DataFrame()
                                    df_net['Foreign_Net'] = df_inst_pivot['buy']['Foreign_Investor'] - df_inst_pivot['sell']['Foreign_Investor']
                                    df_net['Trust_Net'] = df_inst_pivot['buy']['Investment_Trust'] - df_inst_pivot['sell']['Investment_Trust']
                                    df_net['Dealer_Net'] = df_inst_pivot['buy']['Dealer_Self_Analysis'] - df_inst_pivot['sell']['Dealer_Self_Analysis'] # 自營商(自行買賣)
                                    
                                    # 合併進主資料
                                    df = pd.merge(df, df_net, left_on='Date', right_index=True, how='left')

                                # B. 下載融資融券
                                df_margin = fm.taiwan_stock_margin_purchase_short_sale(
                                    stock_id=stock_id_only, start_date=start_date
                                )
                                if not df_margin.empty:
                                    df_margin['date'] = pd.to_datetime(df_margin['date'])
                                    df_margin.set_index('date', inplace=True)
                                    
                                    # 只取需要的欄位：融資餘額 (MarginPurchaseTodayBalance)
                                    margin_cols = df_margin[['MarginPurchaseTodayBalance', 'ShortSaleTodayBalance']]
                                    margin_cols.columns = ['Margin_Balance', 'Short_Balance'] # 改名
                                    
                                    # 合併
                                    df = pd.merge(df, margin_cols, left_on='Date', right_index=True, how='left')
                                # C. 下載【集保大戶籌碼集中度】(每週更新)
                                try:
                                    # 抓取股權分散表
                                    df_holding = fm.taiwan_stock_holding_shares_per(
                                        stock_id=stock_id_only, 
                                        start_date=start_date
                                    )
                                    
                                    if not df_holding.empty:
                                        df_holding['date'] = pd.to_datetime(df_holding['date'])
                                        
                                        # 轉換欄位格式，確保可以運算
                                        df_holding['percent'] = pd.to_numeric(df_holding['percent'], errors='coerce')
                                        df_holding['HoldingSharesLevel'] = pd.to_numeric(df_holding['HoldingSharesLevel'], errors='coerce')
                                
                                        # 邏輯：計算持有 > 400 張的大戶總比例
                                        # 集保分級中，第 12 級以上通常代表 > 400 張 (依官方定義可能略有變動，但通常取 12-17 級或 14-17 級)
                                        # 這裡示範加總 "12級~17級" (約 400張以上) 的持有比例
                                        # 若要抓 1000 張以上，就改成 >= 14
                                        big_hands = df_holding[df_holding['HoldingSharesLevel'] >= 12].groupby('date')['percent'].sum()
                                        
                                        # 整理成 DataFrame
                                        df_big_hands = pd.DataFrame(big_hands).rename(columns={'percent': 'Big_Hand_Hold_Pct'})
                                        
                                        # 合併進主資料
                                        # 注意：集保是「週資料」，日資料是「日資料」
                                        # 我們用 "how='left'" 並在合併後做 "前值填充 (ffill)"
                                        # 這樣週一到週四就會自動帶入上週五的大戶數據，方便畫圖
                                        df = pd.merge(df, df_big_hands, left_on='Date', right_index=True, how='left')
                                        df['Big_Hand_Hold_Pct'] = df['Big_Hand_Hold_Pct'].ffill()
                                
                                except Exception as e:
                                    print(f"集保數據抓取失敗: {e}")
                                    pass    
                            except Exception as e:
                                print(f"FinMind 數據抓取部分失敗: {e}")
                                # 失敗不影響主流程，繼續存股價
                                pass

                        # ==========================================
                        #  🔥 升級模組：真・主力分析 (集保 + EFI)
                        # ==========================================
                        
                        # --- Part 1: 上帝視角 (集保大戶 vs 散戶) ---
                        # 這是最準確的籌碼指標，不管主力是誰都逃不過
                        try:
                            # 抓取每週股權分散表
                            df_holding = fm.taiwan_stock_holding_shares_per(
                                stock_id=stock_id_only, 
                                start_date=start_date
                            )
                            
                            if not df_holding.empty:
                                df_holding['date'] = pd.to_datetime(df_holding['date'])
                                df_holding['percent'] = pd.to_numeric(df_holding['percent'], errors='coerce')
                                df_holding['HoldingSharesLevel'] = pd.to_numeric(df_holding['HoldingSharesLevel'], errors='coerce')

                                # 定義「大戶」：持有 > 400 張 (等級 12 以上)
                                # 定義「散戶」：持有 < 5 張 (等級 1~3)
                                # 注意：等級劃分依集保定義，12級通常為 400,001-600,000
                                
                                # 計算大戶持股比例
                                big_hands = df_holding[df_holding['HoldingSharesLevel'] >= 12].groupby('date')['percent'].sum()
                                
                                # 計算散戶持股比例 (螞蟻雄兵，通常是反向指標)
                                small_hands = df_holding[df_holding['HoldingSharesLevel'] <= 3].groupby('date')['percent'].sum()
                                
                                df_dist = pd.DataFrame({
                                    'Big_Hands_Pct': big_hands,
                                    'Small_Hands_Pct': small_hands
                                })
                                
                                # 算出「籌碼集中度差值」：大戶 - 散戶
                                # 數值由負轉正 = 主力進場、散戶退場 (最佳買點)
                                df_dist['Chip_Spread'] = df_dist['Big_Hands_Pct'] - df_dist['Small_Hands_Pct']
                                
                                # 合併 (注意集保是週資料，需用 ffill 填補到日線)
                                df = pd.merge(df, df_dist, left_on='Date', right_index=True, how='left')
                                df['Big_Hands_Pct'] = df['Big_Hands_Pct'].ffill()
                                df['Small_Hands_Pct'] = df['Small_Hands_Pct'].ffill()
                                df['Chip_Spread'] = df['Chip_Spread'].ffill()
                                
                        except Exception as e:
                            print(f"集保數據運算錯誤: {e}")
                            pass

                        # --- Part 2: 數學主力 (Elder's Force Index) ---
                        # 就算沒有籌碼數據，也能用「價量」算出主力力道
                        # 公式：(今日收盤 - 昨日收盤) * 成交量
                        
                        # 確保 Volume 是數值
                        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').fillna(0)
                        
                        # 1. 原始力道 (Raw Force)
                        close_diff = df['Close'].diff()
                        df['Raw_Force'] = close_diff * df['Volume']
                        
                        # 2. 埃爾德強力指標 (EFI 13日) - 適合波段
                        # EFI > 0 且上升：主力買進力道強
                        # EFI < 0：主力賣出
                        df['EFI_13'] = df['Raw_Force'].ewm(span=13, adjust=False).mean()
                        
                        # 3. 巨量長紅檢測 (Big Bull Candle)
                        # 邏輯：漲幅 > 3% 且 成交量 > 5日均量 * 1.5
                        vol_ma5 = df['Volume'].rolling(5).mean()
                        df['Is_Big_Bull'] = (
                            (df['Close'].pct_change() > 0.03) & 
                            (df['Volume'] > vol_ma5 * 1.5)
                        ).astype(int)

                        # ==========================================
                        
                        # 最後填補與輸出
                        cols_needed = ['Big_Hands_Pct', 'Small_Hands_Pct', 'Chip_Spread', 'EFI_13']
                        for c in cols_needed:
                            if c not in df.columns: df[c] = 0
                            else: df[c] = df[c].fillna(0)
                                
                        # 3. 轉成 CSV 並寫入 ZIP
                        # 填補 NaN (因為籌碼資料可能有缺漏日期)
                        df.fillna(0, inplace=True)
                        csv_data = df.to_csv(index=False).encode('utf-8-sig')
                        zf.writestr(f"{real_ticker}.csv", csv_data)
                        success_count += 1
                        
                    else:
                        st.error(f"❌ {real_ticker} 查無資料")
                        
                except Exception as e:
                    st.error(f"❌ {real_ticker} 下載失敗: {e}")

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
