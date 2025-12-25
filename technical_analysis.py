# filename: technical_analysis.py

import yfinance as yf
import mplfinance as mpf
import pandas as pd
import numpy as np

def calculate_all_indicators(df):
    """
    核心運算引擎：計算所有技術指標
    包含：MA, BB, ATR, Ichimoku, RSI, KD, MACD, OBV, DMI
    """
    # 1. 基礎數據清洗
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # 2. 均線系統 (Moving Averages)
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA10'] = df['Close'].rolling(window=10).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()

    # 3. 布林通道 (Bollinger Bands)
    df['std20'] = df['Close'].rolling(window=20).std()
    df['BB_Up'] = df['MA20'] + (2 * df['std20'])
    df['BB_Lo'] = df['MA20'] - (2 * df['std20'])

    # 4. ATR 與 停損線 (Chandelier Exit)
    prev_close = df['Close'].shift(1)
    df['H-L'] = df['High'] - df['Low']
    df['H-PC'] = abs(df['High'] - prev_close)
    df['L-PC'] = abs(df['Low'] - prev_close)
    df['TR'] = df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    df['ATR'] = df['TR'].rolling(window=14).mean()
    df['ATR_Stop'] = df['Close'] - (2 * df['ATR'])

    # 5. 一目均衡表 (Ichimoku) - 簡化版
    # 轉換線 (Tenkan) & 基準線 (Kijun)
    df['Tenkan'] = (df['High'].rolling(window=9).max() + df['Low'].rolling(window=9).min()) / 2
    df['Kijun'] = (df['High'].rolling(window=26).max() + df['Low'].rolling(window=26).min()) / 2

    # 6. RSI (Relative Strength Index)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # 7. KD (Stochastic)
    low_min = df['Low'].rolling(window=9).min()
    high_max = df['High'].rolling(window=9).max()
    df['RSV'] = (df['Close'] - low_min) / (high_max - low_min) * 100
    df['K'] = df['RSV'].ewm(com=2).mean()
    df['D'] = df['K'].ewm(com=2).mean()

    # 8. MACD
    exp12 = df['Close'].ewm(span=12, adjust=False).mean()
    exp26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp12 - exp26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']

    # 9. OBV (On-Balance Volume)
    df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()

    # 10. DMI & ADX
    up = df['High'].diff()
    down = -df['Low'].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr_smooth = df['TR'].rolling(window=14).mean()
    df['+DI'] = 100 * (pd.Series(plus_dm).rolling(window=14).mean() / tr_smooth)
    df['-DI'] = 100 * (pd.Series(minus_dm).rolling(window=14).mean() / tr_smooth)
    df['DX'] = 100 * abs(df['+DI'] - df['-DI']) / (df['+DI'] + df['-DI'])
    df['ADX'] = df['DX'].rolling(window=14).mean()

    return df

def plot_single_chart(ticker, df, title_suffix, timeframe_label):
    """繪製單張圖表 (包含 5 個面板)"""
    
    # 裁切數據: 週線看 100 根 (約2年), 日線看 120 根 (約半年)
    bars = 100 if timeframe_label == 'Weekly' else 120
    plot_df = df.tail(bars).copy()

    # 設定面板 (Subplots)
    apds = [
        # Panel 0: 主圖 (MA + BB + Ichimoku + ATR)
        mpf.make_addplot(plot_df[['MA5', 'MA10', 'MA20']], ax=None, width=1.0),
        mpf.make_addplot(plot_df['MA60'], color='black', width=1.5), 
        mpf.make_addplot(plot_df['BB_Up'], color='gray', linestyle='--', alpha=0.5),
        mpf.make_addplot(plot_df['BB_Lo'], color='gray', linestyle='--', alpha=0.5),
        mpf.make_addplot(plot_df['Tenkan'], color='cyan', linestyle=':', width=0.8),
        mpf.make_addplot(plot_df['Kijun'], color='brown', linestyle=':', width=0.8),
        mpf.make_addplot(plot_df['ATR_Stop'], color='purple', type='scatter', markersize=6, marker='_'),
        
        # Panel 1: OBV (與成交量分開，看趨勢)
        mpf.make_addplot(plot_df['OBV'], panel=1, color='blue', title='OBV', width=1.2),

        # Panel 2: MACD
        mpf.make_addplot(plot_df['Hist'], type='bar', panel=2, color='dimgray', alpha=0.5, title='MACD'),
        mpf.make_addplot(plot_df['MACD'], panel=2, color='fuchsia'),
        mpf.make_addplot(plot_df['Signal'], panel=2, color='c'),

        # Panel 3: KD & RSI
        mpf.make_addplot(plot_df['K'], panel=3, color='orange', title='KD & RSI'),
        mpf.make_addplot(plot_df['D'], panel=3, color='blue'),
        mpf.make_addplot(plot_df['RSI'], panel=3, color='green', linestyle='--', width=1),
        
        # Panel 4: DMI
        mpf.make_addplot(plot_df['ADX'], panel=4, color='black', width=1.5, title='DMI (ADX)'),
        mpf.make_addplot(plot_df['+DI'], panel=4, color='red', width=0.8),
        mpf.make_addplot(plot_df['-DI'], panel=4, color='green', width=0.8),
    ]

    mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
    s = mpf.make_mpf_style(marketcolors=mc, style='yahoo', grid_style=':')

    print(f"📊 正在繪製 {timeframe_label} 全方位分析圖...")
    
    mpf.plot(plot_df, type='candle', style=s, addplot=apds, 
             volume=True, 
             panel_ratios=(4, 1, 1, 1, 1, 1), # 調整比例以容納更多面板
             title=f"{ticker} {title_suffix} ({timeframe_label})", 
             figsize=(12, 14), # 長條形圖表，方便手機滑動觀看
             tight_layout=True)

def plot_dual_timeframe(ticker_symbol):
    """
    主程式：執行 [週線] + [日線] 雙重分析
    """
    ticker_symbol = str(ticker_symbol).strip()
    if ticker_symbol.isdigit():
        ticker = f"{ticker_symbol}.TW"
    else:
        ticker = ticker_symbol.upper()

    print(f"🚀 啟動雙週期全方位分析引擎: {ticker}")

    # 1. 週線 (Weekly) - 抓 3 年
    try:
        df_week = yf.download(ticker, period='3y', interval='1wk', progress=False)
        if not df_week.empty:
            df_week = calculate_all_indicators(df_week)
            plot_single_chart(ticker, df_week, "Trend (Long)", "Weekly")
        else:
            print("❌ 無法下載週線數據")
    except Exception as e:
        print(f"❌ 週線下載錯誤: {e}")

    # 2. 日線 (Daily) - 抓 1 年
    try:
        df_day = yf.download(ticker, period='1y', interval='1d', progress=False)
        if not df_day.empty:
            df_day = calculate_all_indicators(df_day)
            plot_single_chart(ticker, df_day, "Action (Short)", "Daily")
        else:
            print("❌ 無法下載日線數據")
    except Exception as e:
        print(f"❌ 日線下載錯誤: {e}")

if __name__ == "__main__":
    # 測試用
    plot_dual_timeframe('2330')
