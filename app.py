import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# 設定網頁標題
st.title('📈 台股/美股 歷史資料下載器')
st.markdown("輸入股票代號，下載 CSV 後，上傳給 Gemini 進行全方位分析。")

# 1. 輸入區塊
col1, col2 = st.columns(2)
with col1:
    ticker_input = st.text_input("輸入股票代號 (例如: 2330.TW 或 NVDA)", value="2330.TW")
with col2:
    period = st.selectbox("選擇時間長度", ["1y", "3y", "5y", "10y", "max"], index=1)

# 按鈕觸發
if st.button('🚀 抓取資料'):
    # 自動補全台股代號
    ticker = ticker_input.strip().upper()
    if ticker.isdigit():
        ticker = f"{ticker}.TW"
    
    st.info(f"正在從 Yahoo Finance 下載 {ticker} ...")
    
    try:
        # 下載數據
        df = yf.download(ticker, period=period, interval="1d", progress=False)
        
        if df.empty:
            st.error(f"❌ 找不到 {ticker} 的資料，請檢查代號。")
        else:
            # 清洗 MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 重設索引，讓 Date 變成一個欄位 (方便 CSV 閱讀)
            df.reset_index(inplace=True)
            
            # 預覽數據
            st.success(f"✅ 成功取得 {len(df)} 筆交易資料！")
            st.dataframe(df.tail()) # 顯示最後幾筆

            # 轉換為 CSV
            csv = df.to_csv(index=False).encode('utf-8-sig') # utf-8-sig 避免 Excel 開啟亂碼
            
            # 下載按鈕
            filename = f"{ticker}_{datetime.now().strftime('%Y%m%d')}.csv"
            st.download_button(
                label="📥 點擊下載 CSV 檔案",
                data=csv,
                file_name=filename,
                mime='text/csv',
            )
            
    except Exception as e:
        st.error(f"發生錯誤: {e}")
