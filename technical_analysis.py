# filename: technical_analysis.py

import yfinance as yf
import mplfinance as mpf
import pandas as pd
import numpy as np

def plot_ultimate_chart(ticker_symbol, period='1y'):
    """
    繪製包含朱家泓戰法與全方位技術指標的 K 線圖。
    包含：均線、布林通道、ATR 停損、一目均衡表、成交量、OBV、MACD、KD、RSI、DMI。
    """
    
    # 1. 處理代號 (自動補上 .TW)
    ticker_symbol = str(ticker_symbol).strip()
    if ticker_symbol.isdigit():
        ticker = f"{ticker_symbol}.TW"
    else:
        ticker = ticker_symbol.upper()

    print(f"🔄 正在從 yfinance 下載 {ticker} 數據...")
    
    try:
        df = yf.download(ticker, period=period, progress=False)
    except Exception as e:
        print(f"❌ 下載失敗: {e}")
        return

    if df.empty:
        print(f"❌ 找不到 {ticker} 的資料，請確認代號是否正確。")
        return

    # 處理 MultiIndex (新版 yfinance 可能會出現的問題)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # ==========================================
    # 2. 指標運算核心 (Manual Calculation)
    # ==========================================
    
    # A. 基礎均線 (MA)
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA10'] = df['Close'].rolling(window=10).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()

    # B. 布林通道 (Bollinger Bands)
    df['std20'] = df['Close'].rolling(window=20).std()
    df['BB_Up'] = df['MA20'] + (2 * df['std20'])
    df['BB_Lo'] = df['MA20'] - (2 * df['std20'])

    # C. ATR 與 停損線 (Chandelier Exit concept)
    # TR = Max(H-L, |H-Cp|, |L-Cp|)
    prev_close = df['Close'].shift(1)
    df['H-L'] = df['High'] - df['Low']
    df['H-PC'] = abs(df['High'] - prev_close)
    df['L-PC'] = abs(df['Low'] - prev_close)
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['ATR'] = df['TR'].rolling(window=14).mean()
    # 畫出「ATR 2倍停損線」(畫在收盤價下方)
    df['ATR_Stop'] = df['Close'] - (2 * df['ATR'])

    # D. 一目均衡表 (Ichimoku) - 簡化版
    # 轉換線 (Tenkan-sen): (9-period high + 9-period low)/2
    high9 = df['High'].rolling(window=9).max()
    low9 = df['Low'].rolling(window=9).min()
    df['Tenkan'] = (high9 + low9) / 2
    # 基準線 (Kijun-sen): (26-period high + 26-period low)/2
    high26 = df['High'].rolling(window=26).max()
    low26 = df['Low'].rolling(window=26).min()
    df['Kijun'] = (high26 + low26) / 2

    # E. RSI (Relative Strength Index)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # F. KD (Stochastic)
    low_min = df['Low'].rolling(window=9).min()
    high_max = df['High'].rolling(window=9).max()
    df['RSV'] = (df['Close'] - low_min) / (high_max - low_min) * 100
    df['K'] = df['RSV'].ewm(com=2).mean()
    df['D'] = df['K'].ewm(com=2).mean()

    # G. MACD
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp12 - exp26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']

    # H. OBV (On-Balance Volume)
    # 若收盤價 > 前日收盤，加成交量；否則減。
    df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()

    # I. DMI & ADX
    up = df['High'].diff()
    down = -df['Low'].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    
    # 平滑計算 (簡易版使用 Rolling)
    tr_smooth = df['TR'].rolling(window=14).mean()
    df['+DI'] = 100 * (pd.Series(plus_dm).rolling(window=14).mean() / tr_smooth)
    df['-DI'] = 100 * (pd.Series(minus_dm).rolling(window=14).mean() / tr_smooth)
    df['DX'] = 100 * abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
    df['ADX'] = df['DX'].rolling(window=14).mean()

    # 裁切數據 (只畫最近 120 天，讓圖形清楚)
    plot_df = df.tail(120).copy()

    # ==========================================
    # 3. 繪圖設定 (Advanced Plotting)
    # ==========================================
    
    # 定義副圖 (Subplots)
    apds = [
        # --- Panel 0: 主圖 (均線 + 通道 + 一目 + ATR) ---
        mpf.make_addplot(plot_df[['MA5', 'MA10', 'MA20']], ax=None, width=1.0),
        mpf.make_addplot(plot_df['MA60'], color='black', width=1.5), 
        mpf.make_addplot(plot_df['BB_Up'], color='gray', linestyle='--', alpha=0.5),
        mpf.make_addplot(plot_df['BB_Lo'], color='gray', linestyle='--', alpha=0.5),
        mpf.make_addplot(plot_df['Tenkan'], color='cyan', linestyle=':', width=0.8),
        mpf.make_addplot(plot_df['Kijun'], color='brown', linestyle=':', width=0.8),
        mpf.make_addplot(plot_df['ATR_Stop'], color='purple', type='scatter', markersize=8, marker='_'),
        
        # --- Panel 1: OBV ---
        mpf.make_addplot(plot_df['OBV'], panel=1, color='blue', title='Volume & OBV'),

        # --- Panel 2: MACD ---
        mpf.make_addplot(plot_df['Hist'], type='bar', panel=2, color='dimgray', alpha=0.5, title='MACD'),
        mpf.make_addplot(plot_df['MACD'], panel=2, color='fuchsia'),
        mpf.make_addplot(plot_df['Signal'], panel=2, color='c'),

        # --- Panel 3: KD & RSI ---
        mpf.make_addplot(plot_df['K'], panel=3, color='orange', title='KD & RSI'),
        mpf.make_addplot(plot_df['D'], panel=3, color='blue'),
        mpf.make_addplot(plot_df['RSI'], panel=3, color='green', linestyle='--', width=1),
        
        # --- Panel 4: DMI ---
        mpf.make_addplot(plot_df['ADX'], panel=4, color='black', width=1.5, title='DMI (ADX)'),
        mpf.make_addplot(plot_df['+DI'], panel=4, color='red', width=0.8),
        mpf.make_addplot(plot_df['-DI'], panel=4, color='green', width=0.8),
    ]

    # 風格設定
    mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
    s = mpf.make_mpf_style(marketcolors=mc, style='yahoo', grid_style=':')

    print(f"✅ 數據計算完成，正在繪圖...")
    
    # 產生圖表
    mpf.plot(plot_df, type='candle', style=s, addplot=apds, 
             volume=True, 
             panel_ratios=(4, 1, 1, 1, 1), 
             title=f"{ticker} Ultimate Technical Analysis", 
             figsize=(12, 14), 
             tight_layout=True)

if __name__ == "__main__":
    # 本地測試用 (Gemini 不會執行這行)
    plot_ultimate_chart('2330')
