import streamlit as st
import pandas as pd
import io
import re
import altair as alt
import os
import psutil
import gc
from itertools import islice
import hashlib
import time
try:
    import vl_convert as vlc
except ImportError:
    vlc = None

# --- Configuration Management ---
class AppConfig:
    """Central configuration for the application."""
    CHUNK_SIZE = 10000
    MAX_PREVIEW_ROWS = 10000
    BINARY_CHECK_BYTES = 4096
    RATE_LIMIT_SECONDS = 1.0
    IP_HASH_LENGTH = 12
    PNG_SCALE = 2
    # Regex for Apache/Nginx Combined Log Format
    LOG_PATTERN = r'(?P<ip_address>\S+) \S+ \S+ \[(?P<timestamp>.*?)\] "(?P<method>\S+) (?P<page_visited>\S+) \S+" (?P<status_code>\d{3}) (?P<data_size>\S+)(?: "(?P<referer>.*?)" "(?P<user_agent>.*?)")?'

# Page Configuration
st.set_page_config(
    page_title="Website Traffic Analysis",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Website Traffic Log Analysis")
st.markdown("""
This application allows you to upload raw website traffic logs (CSV) and automatically performs 
**ETL (Extract, Transform, Load)** operations to visualize user behavior and identify issues. Supports **CSV** and **Apache/Nginx Access Logs**.
""")

# --- Security: Rate Limiting ---
if 'last_request_time' not in st.session_state:
    st.session_state.last_request_time = 0

if time.time() - st.session_state.last_request_time < AppConfig.RATE_LIMIT_SECONDS:
    st.warning("⚠️ Rate limit exceeded. Please wait a moment.")
    st.stop()
st.session_state.last_request_time = time.time()

# --- ETL Functions ---

def load_data(file):
    """Extract: Load data from uploaded file."""
    if file is not None:
        try:
            file.seek(0)
            # Security: Basic Input Sanitization (Check for binary files)
            if b'\0' in file.read(AppConfig.BINARY_CHECK_BYTES):
                st.error("Invalid file format: Binary content detected.")
                return None
            file.seek(0)
            # Handle CSV
            if file.name.endswith('.csv'):
                # Use chunking to handle large CSVs more gracefully during load
                # Although we concat immediately, this avoids some internal buffering issues with massive files
                chunks = pd.read_csv(file, chunksize=AppConfig.CHUNK_SIZE)
                return pd.concat(chunks, ignore_index=True)
            
            # Handle Real-world Logs (Apache/Nginx Combined Format)
            # Format: IP - - [Date] "Method Path Protocol" Status Size "Referer" "UserAgent"
            elif file.name.endswith('.log') or file.name.endswith('.txt'):
                # Optimize: Process file in chunks to avoid loading full content into memory
                # This combines the speed of vectorized regex with the memory efficiency of streaming

                # Regex to extract fields (Supports Combined and Common Log Format)
                # Made Referer and User Agent optional to support NASA CLF logs
                log_pattern = AppConfig.LOG_PATTERN
                
                chunks = []
                text_stream = io.TextIOWrapper(file, encoding='utf-8', errors='replace')
                
                while True:
                    lines = list(islice(text_stream, AppConfig.CHUNK_SIZE))
                    if not lines:
                        break
                    
                    df_chunk = pd.Series(lines)
                    extracted = df_chunk.str.extract(log_pattern)
                    extracted = extracted.dropna(how='all')
                    if not extracted.empty:
                        chunks.append(extracted)
                
                text_stream.detach()
                
                if chunks:
                    data = pd.concat(chunks, ignore_index=True)
                    # Fix timestamp format for Pandas
                    data['timestamp'] = data['timestamp'].str.replace(':', ' ', n=1)
                    return data
                else:
                    st.error("No valid log lines found. Ensure format is Apache/Nginx Combined.")
                    return None
                    
        except Exception as e:
            st.error(f"Error processing file: {e}")
            return None
    return None

def transform_data(df, anonymize_ip=False):
    """Transform: Clean and feature engineer the data."""
    try:
        # Copy to avoid SettingWithCopy warnings
        df = df.copy()
        
        # Security: IP Anonymization (GDPR)
        if anonymize_ip and 'ip_address' in df.columns:
            df['ip_address'] = df['ip_address'].astype(str).apply(
                lambda x: hashlib.sha256(x.encode()).hexdigest()[:AppConfig.IP_HASH_LENGTH]
            )

        # Map 'minute' to 'timestamp' if present (handling aggregated datasets)
        if 'minute' in df.columns:
            df = df.rename(columns={'minute': 'timestamp'})

        # Convert timestamp
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            
            # Drop rows with invalid timestamps
            df = df.dropna(subset=['timestamp'])
            
            # Extract features
            df['hour_of_day'] = df['timestamp'].dt.hour
        
        # Ensure status_code is int
        if 'status_code' in df.columns:
            df['status_code'] = pd.to_numeric(df['status_code'], errors='coerce').fillna(0).astype(int)
            
            # Categorize Status Codes for easier analysis
            df['status_category'] = 'Other'
            df.loc[(df['status_code'] >= 200) & (df['status_code'] < 300), 'status_category'] = 'Success (2xx)'
            df.loc[(df['status_code'] >= 300) & (df['status_code'] < 400), 'status_category'] = 'Redirect (3xx)'
            df.loc[(df['status_code'] >= 400) & (df['status_code'] < 500), 'status_category'] = 'Client Error (4xx)'
            df.loc[(df['status_code'] >= 500) & (df['status_code'] < 600), 'status_category'] = 'Server Error (5xx)'
        
        # Clean data_size (replace '-' with 0 and convert to numeric)
        if 'data_size' in df.columns:
            df['data_size'] = pd.to_numeric(df['data_size'], errors='coerce').fillna(0)
        
        # Clean referer
        if 'referer' in df.columns:
            df['referer'] = df['referer'].fillna('-')
        
        # Extract Day of Week
        if 'timestamp' in df.columns:
            df['day_of_week'] = df['timestamp'].dt.day_name()

        # Parse User Agent for Browser
        if 'user_agent' in df.columns:
            # Optimize: Use vectorized string operations instead of apply() for performance
            ua = df['user_agent'].astype(str).str.lower()
            df['browser'] = 'Other'
            
            df.loc[ua.str.contains('safari'), 'browser'] = 'Safari'
            df.loc[ua.str.contains('firefox'), 'browser'] = 'Firefox'
            df.loc[ua.str.contains('chrome'), 'browser'] = 'Chrome'
            df.loc[ua.str.contains('edge'), 'browser'] = 'Edge'
            df.loc[ua.str.contains('bot|crawl', regex=True), 'browser'] = 'Bot'

        return df
    except Exception as e:
        st.error(f"Error during transformation: {e}")
        return None

def convert_df(df):
    # Cache the conversion to prevent reloading on every interaction
    return df.to_csv(index=False).encode('utf-8')

def add_download_button(chart, filename, key):
    """Helper to add a download button for an Altair chart."""
    if vlc:
        try:
            png_bytes = vlc.vegalite_to_png(chart.to_json(), scale=AppConfig.PNG_SCALE)
            st.download_button(label="💾", data=png_bytes, file_name=f"{filename}.png", mime="image/png", key=key, help="Download as PNG")
        except Exception:
            pass # Fail silently if conversion fails

def validate_data(df, required_cols):
    """Validate that the dataframe contains the required columns."""
    missing = set(required_cols) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    return True

# --- Sidebar / Input ---

st.sidebar.header("Data Input")

if st.sidebar.button("Reset Dashboard", type="primary"):
    st.session_state.clear()
    st.rerun()

anonymize = st.sidebar.checkbox("Anonymize IPs (GDPR)", value=True, help="Hash IP addresses to protect user privacy.")
uploaded_file = st.sidebar.file_uploader("Upload Log (CSV, LOG, TXT)", type=['csv', 'log', 'txt'], key="file_uploader")

# Sample Data Fallback
SAMPLE_CSV = """timestamp,ip_address,page_visited,status_code,user_agent
2023-10-26 08:00:01,192.168.1.1,/home,200,Chrome
2023-10-26 08:02:02,10.0.0.5,/products,200,Firefox
2023-10-26 08:04:01,172.16.0.10,/about,200,Safari
2023-10-26 08:06:03,192.168.1.2,/contact,200,Edge
2023-10-26 08:14:03,172.16.0.10,/home,404,Edge
2023-10-26 08:26:02,192.168.1.2,/search?q=data,500,Firefox
"""

if not uploaded_file:
    st.info("Awaiting upload. Using sample data for demonstration.")
    df_raw = pd.read_csv(io.StringIO(SAMPLE_CSV))
else:
    st.toast("File upload detected. Starting processing...", icon="⏳")
    df_raw = load_data(uploaded_file)
    if df_raw is not None:
        # st.success("Data upload completed")
        st.toast("Analysis completed!", icon="✅")

# --- Main Execution ---

if df_raw is not None:
    # Data Validation
    try:
        # Ensure we have at least a time column for analysis
        # We check for 'minute' (LSTM dataset) or 'timestamp' (Standard logs/CSV)
        if 'minute' in df_raw.columns:
            validate_data(df_raw, ['minute'])
        else:
            validate_data(df_raw, ['timestamp'])
    except ValueError as e:
        st.error(f"Validation Failed: {e}")
        st.stop()

    # Transform
    df_clean = transform_data(df_raw, anonymize)
    
    # Free up memory
    del df_raw
    gc.collect()
    
    if df_clean is not None:
        st.toast(f"Analysis completed! {len(df_clean):,} rows.", icon="✅")
        st.success(f"Analysis completed successfully on {len(df_clean):,} rows.")
        # --- Date Filter ---
        st.sidebar.header("Filters")
        
        if not df_clean.empty:
            min_date = df_clean['timestamp'].min().date()
            max_date = df_clean['timestamp'].max().date()
            
            date_range = st.sidebar.date_input(
                "Select Date Range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date
            )
            
            if len(date_range) == 2:
                start_date, end_date = date_range
                df_clean = df_clean[
                    (df_clean['timestamp'].dt.date >= start_date) & 
                    (df_clean['timestamp'].dt.date <= end_date)
                ]

        # --- Dashboard Layout ---
        
        tab1, tab2 = st.tabs(["Dashboard", "Data Overview"])
        
        with tab1:
            # Top Metrics
            st.subheader("Key Metrics")
            col1, col2, col3, col4, col5 = st.columns(5)
            
            total_requests = len(df_clean)
            if 'count' in df_clean.columns:
                 total_requests = df_clean['count'].sum()

            unique_visitors = df_clean['ip_address'].nunique() if 'ip_address' in df_clean.columns else 0
            
            client_error_rate = 0
            server_error_rate = 0
            if 'status_code' in df_clean.columns:
                client_errors = df_clean[(df_clean['status_code'] >= 400) & (df_clean['status_code'] < 500)]
                server_errors = df_clean[(df_clean['status_code'] >= 500) & (df_clean['status_code'] < 600)]
                client_error_rate = (len(client_errors) / len(df_clean)) * 100 if len(df_clean) > 0 else 0
                server_error_rate = (len(server_errors) / len(df_clean)) * 100 if len(df_clean) > 0 else 0
            
            # Calculate total data transfer if available
            if 'data_size' in df_clean.columns:
                total_data_gb = df_clean['data_size'].sum() / (1024**3) # Convert bytes to GB
            else:
                total_data_gb = 0
            
            col1.metric("Total Requests", total_requests)
            col2.metric("Unique Visitors", unique_visitors if unique_visitors > 0 else "N/A")
            col3.metric("4xx Errors", f"{client_error_rate:.2f}%")
            col4.metric("5xx Errors", f"{server_error_rate:.2f}%")
            col5.metric("Data Transferred", f"{total_data_gb:.2f} GB")
            
            # Visualizations
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                st.subheader("Traffic by Hour")
                if 'hour_of_day' in df_clean.columns:
                    # Prepare data for Altair
                    if 'count' in df_clean.columns:
                        hourly_data = df_clean.groupby('hour_of_day')['count'].sum().reset_index()
                    else:
                        hourly_data = df_clean['hour_of_day'].value_counts().reset_index()
                        hourly_data.columns = ['hour_of_day', 'count']
                    
                    if not hourly_data.empty:
                        chart = alt.Chart(hourly_data).mark_bar(color='#4c78a8').encode(
                            x=alt.X('hour_of_day', title='Hour of Day'),
                            y=alt.Y('count', title='Request Count'),
                            tooltip=['hour_of_day', 'count']
                        ).interactive()
                        st.altair_chart(chart, width="stretch")
                        add_download_button(chart, "traffic_by_hour", "dl_traffic_hour")
                
            with col_chart2:
                st.subheader("Top 5 Pages")
                if 'page_visited' in df_clean.columns:
                    top_pages = df_clean['page_visited'].value_counts().head(5).reset_index()
                    top_pages.columns = ['page_visited', 'count']
                    chart = alt.Chart(top_pages).mark_bar().encode(
                        x=alt.X('page_visited', sort='-y', title='Page'),
                        y=alt.Y('count', title='Visits'),
                        tooltip=['page_visited', 'count']
                    ).interactive()
                    st.altair_chart(chart, width="stretch")
                    add_download_button(chart, "top_pages", "dl_top_pages")
                else:
                    st.info("Page information not available.")
                
            # New Analysis Sections
            col_chart3, col_chart4 = st.columns(2)
            
            with col_chart3:
                st.subheader("Daily Traffic Trend")
                if 'timestamp' in df_clean.columns:
                    if 'count' in df_clean.columns:
                        daily_data = df_clean.set_index('timestamp').resample('D')['count'].sum().reset_index()
                    else:
                        daily_data = df_clean.set_index('timestamp').resample('D').size().reset_index(name='count')
                    
                    if not daily_data.empty:
                        chart = alt.Chart(daily_data).mark_line(color='#55a868').encode(
                            x=alt.X('timestamp', title='Date'),
                            y=alt.Y('count', title='Requests'),
                            tooltip=['timestamp', 'count']
                        ).interactive()
                        st.altair_chart(chart, width="stretch")
                        add_download_button(chart, "daily_traffic", "dl_daily_traffic")

            with col_chart4:
                st.subheader("Top 404 Errors (Missing Pages)")
                if 'status_code' in df_clean.columns and 'page_visited' in df_clean.columns:
                    missing_pages = df_clean[df_clean['status_code'] == 404]['page_visited'].value_counts().head(5).reset_index()
                    missing_pages.columns = ['page_visited', 'count']
                    chart = alt.Chart(missing_pages).mark_bar(color='orange').encode(
                        x=alt.X('page_visited', sort='-y', title='Page'),
                        y=alt.Y('count', title='Errors'),
                        tooltip=['page_visited', 'count']
                    ).interactive()
                    st.altair_chart(chart, width="stretch")
                    add_download_button(chart, "missing_pages", "dl_missing_pages")
                else:
                    st.info("404 Error analysis not available.")

            # --- Anomaly Detection ---
            st.markdown("---")
            st.subheader("🚨 Anomaly Detection")
            if 'hour_of_day' in df_clean.columns:
                # Calculate hourly counts
                if 'count' in df_clean.columns:
                    hourly_counts = df_clean.groupby('hour_of_day')['count'].sum()
                else:
                    hourly_counts = df_clean['hour_of_day'].value_counts().sort_index()
                
                if not hourly_counts.empty:
                    mean_traffic = hourly_counts.mean()
                    std_traffic = hourly_counts.std()
                    # Flag hours with traffic > Mean + 2 Standard Deviations
                    threshold = mean_traffic + (2 * std_traffic) 
                    
                    anomalies = hourly_counts[hourly_counts > threshold]
                    
                    if not anomalies.empty:
                        st.warning(f"⚠️ High traffic anomalies detected at hours: {', '.join(map(str, anomalies.index.tolist()))}")
                        st.caption(f"These hours exceeded the threshold of {int(threshold)} requests (Mean + 2σ).")
                    else:
                        st.success("✅ No significant traffic anomalies detected (all traffic within normal range).")
            else:
                st.info("Hourly data required for anomaly detection.")

            # --- Advanced Insights (New Charts) ---
            st.markdown("---")
            st.subheader("🔍 Advanced Insights")
            col_adv1, col_adv2 = st.columns(2)

            with col_adv1:
                st.markdown("**Weekly Activity Heatmap**")
                if 'day_of_week' in df_clean.columns and 'hour_of_day' in df_clean.columns:
                    if 'count' in df_clean.columns:
                        heatmap_data = df_clean.groupby(['day_of_week', 'hour_of_day'])['count'].sum().reset_index()
                    else:
                        heatmap_data = df_clean.groupby(['day_of_week', 'hour_of_day']).size().reset_index(name='count')
                    
                    # Sort days correctly
                    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    
                    if not heatmap_data.empty:
                        chart = alt.Chart(heatmap_data).mark_rect().encode(
                            x=alt.X('hour_of_day:O', title='Hour'),
                            y=alt.Y('day_of_week:O', title='Day', sort=days_order),
                            color=alt.Color('count:Q', scale=alt.Scale(scheme='viridis'), title='Requests'),
                            tooltip=['day_of_week', 'hour_of_day', 'count']
                        ).properties(height=300)
                        st.altair_chart(chart, width="stretch")
                        add_download_button(chart, "weekly_heatmap", "dl_heatmap")
                else:
                    st.info("Timestamp data required for heatmap.")

            with col_adv2:
                st.markdown("**Browser Distribution**")
                if 'browser' in df_clean.columns:
                    browser_data = df_clean['browser'].value_counts().reset_index()
                    browser_data.columns = ['browser', 'count']
                    
                    if not browser_data.empty:
                        chart = alt.Chart(browser_data).mark_arc(innerRadius=60).encode(
                            theta=alt.Theta(field="count", type="quantitative"),
                            color=alt.Color(field="browser", type="nominal", scale=alt.Scale(scheme='category10')),
                            tooltip=['browser', 'count']
                        ).properties(height=300)
                        st.altair_chart(chart, width="stretch")
                        add_download_button(chart, "browser_dist", "dl_browser")
                else:
                    st.info("User Agent data required for browser analysis.")

            # Referer Analysis
            st.subheader("Top Referrers")
            if 'referer' in df_clean.columns:
                # Exclude direct traffic ('-')
                top_referers = df_clean[df_clean['referer'] != '-']['referer'].value_counts().head(10).reset_index()
                top_referers.columns = ['referer', 'count']
                chart = alt.Chart(top_referers).mark_bar().encode(
                    x=alt.X('count', title='Visits'),
                    y=alt.Y('referer', sort='-x', title='Referrer'),
                    tooltip=['referer', 'count']
                ).interactive()
                st.altair_chart(chart, width="stretch")
                add_download_button(chart, "top_referers", "dl_referers")

            # Hotlinking Analysis
            st.subheader("Potential Hotlinking (Image Requests)")
            if 'referer' in df_clean.columns:
                # Identify requests for image files
                image_extensions = r'\.(?:png|jpg|jpeg|gif|svg|ico|webp)(?:\?|$)'
                image_requests = df_clean[
                    df_clean['page_visited'].str.contains(image_extensions, case=False, regex=True)
                ]
                
                if not image_requests.empty:
                    # Exclude direct traffic ('-') to find potential hotlinkers
                    hotlink_referers = image_requests[image_requests['referer'] != '-']['referer'].value_counts().head(10).reset_index()
                    hotlink_referers.columns = ['referer', 'count']
                    if not hotlink_referers.empty:
                        chart = alt.Chart(hotlink_referers).mark_bar(color='red').encode(
                            x=alt.X('count', title='Requests'),
                            y=alt.Y('referer', sort='-x', title='Referrer'),
                            tooltip=['referer', 'count']
                        ).interactive()
                        st.altair_chart(chart, width="stretch")
                        add_download_button(chart, "hotlinking", "dl_hotlink")
                        st.caption("Domains listed here (other than your own) might be hotlinking your images.")
                    else:
                        st.info("No external referers found for image requests.")
                else:
                    st.info("No image requests detected.")

            st.subheader("HTTP Status Code Distribution")
            if 'status_code' in df_clean.columns:
                status_counts = df_clean['status_code'].value_counts().reset_index()
                status_counts.columns = ['status_code', 'count']
                
                # Add category for coloring
                def get_cat(code):
                    if 200 <= code < 300: return 'Success (2xx)'
                    if 300 <= code < 400: return 'Redirect (3xx)'
                    if 400 <= code < 500: return 'Client Error (4xx)'
                    if 500 <= code < 600: return 'Server Error (5xx)'
                    return 'Other'
                status_counts['category'] = status_counts['status_code'].apply(get_cat)

                chart = alt.Chart(status_counts).mark_bar().encode(
                    x=alt.X('status_code:O', title='Status Code'),
                    y=alt.Y('count', title='Count'),
                    color=alt.Color('category', scale=alt.Scale(domain=['Success (2xx)', 'Redirect (3xx)', 'Client Error (4xx)', 'Server Error (5xx)', 'Other'], range=['green', 'blue', 'orange', 'red', 'gray']), title='Category'),
                    tooltip=['status_code', 'count']
                ).interactive()
                st.altair_chart(chart, width="stretch")
                add_download_button(chart, "status_codes", "dl_status_codes")
            else:
                st.info("Status code information not available.")

            # Detailed Data View
            with st.expander("View Detailed Data"):
                st.dataframe(df_clean.head(AppConfig.MAX_PREVIEW_ROWS))
                if len(df_clean) > AppConfig.MAX_PREVIEW_ROWS:
                    st.caption(f"⚠️ Displaying only the first {AppConfig.MAX_PREVIEW_ROWS:,} rows for performance. Download the CSV for the full dataset.")
            
            # Load (Download)
            st.subheader("Export Data")
            csv = convert_df(df_clean)
            st.download_button(
                label="Download Processed CSV",
                data=csv,
                file_name='processed_website_logs.csv',
                mime='text/csv',
            )

        with tab2:
            st.header("📁 Data Overview & Analysis Report")
            
            # File Statistics
            st.subheader("File Statistics")
            col1, col2 = st.columns(2)
            col1.info(f"**Rows:** {len(df_clean)}")
            col2.info(f"**Columns:** {len(df_clean.columns)}")
            
            # Column Details
            st.subheader("Column Structure")
            dtypes_df = pd.DataFrame(df_clean.dtypes, columns=['Data Type']).astype(str)
            st.dataframe(dtypes_df)
            
            # Data Quality Metrics
            st.subheader("Data Quality")
            if not df_clean.empty:
                null_counts = df_clean.isnull().sum()
                null_pct = (null_counts / len(df_clean)) * 100
                quality_df = pd.DataFrame({'Null Count': null_counts, 'Null Percentage (%)': null_pct})
                st.dataframe(quality_df.style.format({'Null Percentage (%)': '{:.2f}'}))
            
            # Analysis Logic Description
            st.subheader("Analysis Logic Applied")
            st.markdown("Based on the columns detected in your file, the following analyses were performed:")
            
            analysis_log = []
            if 'timestamp' in df_clean.columns:
                analysis_log.append("- **Time Series Analysis**: Detected `timestamp`. Traffic trends over time and by hour of day were calculated.")
            if 'status_code' in df_clean.columns:
                analysis_log.append("- **Status Code Distribution**: Detected `status_code`. Success vs. Error rates (4xx/5xx) were analyzed.")
            if 'page_visited' in df_clean.columns:
                analysis_log.append("- **Content Popularity**: Detected `page_visited`. Top visited pages and missing pages (404s) were identified.")
            if 'referer' in df_clean.columns:
                analysis_log.append("- **Referrer Analysis**: Detected `referer`. Top traffic sources and potential hotlinking were analyzed.")
            if 'data_size' in df_clean.columns:
                analysis_log.append("- **Bandwidth Usage**: Detected `data_size`. Total data transfer volume was calculated.")
            if 'ip_address' in df_clean.columns:
                analysis_log.append("- **Visitor Tracking**: Detected `ip_address`. Unique visitor counts were established.")
            if 'user_agent' in df_clean.columns:
                analysis_log.append("- **User Agent Analysis**: Detected `user_agent`. Browser distribution was visualized.")
            
            for log in analysis_log:
                st.markdown(log)
                
            if not analysis_log:
                st.warning("No specific analysis columns detected. Only raw data is available.")

# --- System Monitor ---
st.sidebar.markdown("---")
st.sidebar.subheader("System Monitor")
process = psutil.Process(os.getpid())
memory_usage = process.memory_info().rss / 1024 / 1024  # Convert to MB
st.sidebar.metric("Memory Usage", f"{memory_usage:.2f} MB")