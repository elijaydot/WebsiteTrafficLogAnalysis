import streamlit as st
import pandas as pd
import io
import re
import altair as alt
try:
    import vl_convert as vlc
except ImportError:
    vlc = None

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

# --- ETL Functions ---

@st.cache_data
def load_data(file):
    """Extract: Load data from uploaded file."""
    if file is not None:
        try:
            # Handle CSV
            if file.name.endswith('.csv'):
                return pd.read_csv(file)
            
            # Handle Real-world Logs (Apache/Nginx Combined Format)
            # Format: IP - - [Date] "Method Path Protocol" Status Size "Referer" "UserAgent"
            elif file.name.endswith('.log') or file.name.endswith('.txt'):
                # Optimize: Read file line by line to avoid loading entire content into memory
                file.seek(0)
                
                # Progress Bar Setup
                progress_text = "Parsing log file... Please wait."
                my_bar = st.progress(0, text=progress_text)
                total_size = file.size if file.size > 0 else 1
                bytes_processed = 0

                # Regex to extract fields (Supports Combined and Common Log Format)
                # Made Referer and User Agent optional to support NASA CLF logs
                log_pattern = re.compile(
                    r'(?P<ip_address>\S+) \S+ \S+ \[(?P<timestamp>.*?)\] "(?P<method>\S+) (?P<page_visited>\S+) \S+" (?P<status_code>\d{3}) (?P<data_size>\S+)(?: "(?P<referer>.*?)" "(?P<user_agent>.*?)")?'
                )
                
                data = []
                # Use TextIOWrapper to decode stream on the fly without loading full file to RAM
                # We don't use 'with' to avoid closing the underlying Streamlit file object
                text_stream = io.TextIOWrapper(file, encoding='utf-8', errors='replace')
                
                for i, line in enumerate(text_stream):
                    # Update progress bar
                    bytes_processed += len(line.encode('utf-8'))
                    if i % 5000 == 0:
                        progress = min(bytes_processed / total_size, 1.0)
                        my_bar.progress(progress, text=f"{progress_text} {int(progress*100)}%")

                    match = log_pattern.search(line)
                    if match:
                        row = match.groupdict()
                        # Fix timestamp format for Pandas (replace first : with space)
                        # From: 10/Oct/2000:13:55:36 +0000 -> 10/Oct/2000 13:55:36 +0000
                        row['timestamp'] = row['timestamp'].replace(':', ' ', 1)
                        data.append(row)
                
                # Detach wrapper so it doesn't close the underlying file when garbage collected
                text_stream.detach()
                my_bar.empty()
                
                if data:
                    return pd.DataFrame(data)
                else:
                    st.error("No valid log lines found. Ensure format is Apache/Nginx Combined.")
                    return None
                    
        except Exception as e:
            st.error(f"Error processing file: {e}")
            return None
    return None

def transform_data(df):
    """Transform: Clean and feature engineer the data."""
    try:
        # Copy to avoid SettingWithCopy warnings
        df = df.copy()
        
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
            def parse_browser(ua):
                ua = str(ua).lower()
                if 'chrome' in ua: return 'Chrome'
                elif 'firefox' in ua: return 'Firefox'
                elif 'safari' in ua: return 'Safari'
                elif 'edge' in ua: return 'Edge'
                elif 'bot' in ua or 'crawl' in ua: return 'Bot'
                else: return 'Other'
            df['browser'] = df['user_agent'].apply(parse_browser)

        return df
    except Exception as e:
        st.error(f"Error during transformation: {e}")
        return None

# --- Sidebar / Input ---

st.sidebar.header("Data Input")

if st.sidebar.button("Reset Dashboard", type="primary"):
    st.session_state.clear()
    st.rerun()

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
        st.success("Data upload completed")

# --- Main Execution ---

if df_raw is not None:
    # Transform
    df_clean = transform_data(df_raw)
    
    if df_clean is not None:
        st.toast("Analysis completed!", icon="✅")
        st.success("Analysis completed")
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
            col1, col2, col3, col4 = st.columns(4)
            
            total_requests = len(df_clean)
            if 'count' in df_clean.columns:
                 total_requests = df_clean['count'].sum()

            unique_visitors = df_clean['ip_address'].nunique() if 'ip_address' in df_clean.columns else 0
            
            error_rate = 0
            if 'status_code' in df_clean.columns:
                error_requests = df_clean[df_clean['status_code'] >= 400]
                error_rate = (len(error_requests) / len(df_clean)) * 100 if len(df_clean) > 0 else 0
            
            # Calculate total data transfer if available
            if 'data_size' in df_clean.columns:
                total_data_gb = df_clean['data_size'].sum() / (1024**3) # Convert bytes to GB
            else:
                total_data_gb = 0
            
            col1.metric("Total Requests", total_requests)
            col2.metric("Unique Visitors", unique_visitors if unique_visitors > 0 else "N/A")
            col3.metric("Error Rate", f"{error_rate:.2f}%")
            col4.metric("Data Transferred", f"{total_data_gb:.2f} GB")
            
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
                        st.altair_chart(chart, use_container_width=True)
                
            with col_chart2:
                st.subheader("Top 5 Pages")
                if 'page_visited' in df_clean.columns:
                    top_pages = df_clean['page_visited'].value_counts().head(5)
                    st.bar_chart(top_pages)
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
                        st.altair_chart(chart, use_container_width=True)
                    
                    # Feature: Download Chart as Image
                    if vlc:
                        png_bytes = vlc.vegalite_to_png(chart.to_json(), scale=2)
                        st.download_button("Download Chart Image (PNG)", png_bytes, "daily_traffic.png", "image/png", key="dl_daily")

            with col_chart4:
                st.subheader("Top 404 Errors (Missing Pages)")
                if 'status_code' in df_clean.columns and 'page_visited' in df_clean.columns:
                    missing_pages = df_clean[df_clean['status_code'] == 404]['page_visited'].value_counts().head(5)
                    st.bar_chart(missing_pages)
                else:
                    st.info("404 Error analysis not available.")

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
                        st.altair_chart(chart, use_container_width=True)
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
                        st.altair_chart(chart, use_container_width=True)
                else:
                    st.info("User Agent data required for browser analysis.")

            # Referer Analysis
            st.subheader("Top Referrers")
            if 'referer' in df_clean.columns:
                # Exclude direct traffic ('-')
                top_referers = df_clean[df_clean['referer'] != '-']['referer'].value_counts().head(10)
                st.bar_chart(top_referers)

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
                    hotlink_referers = image_requests[image_requests['referer'] != '-']['referer'].value_counts().head(10)
                    if not hotlink_referers.empty:
                        st.bar_chart(hotlink_referers)
                        st.caption("Domains listed here (other than your own) might be hotlinking your images.")
                    else:
                        st.info("No external referers found for image requests.")
                else:
                    st.info("No image requests detected.")

            st.subheader("HTTP Status Code Distribution")
            if 'status_code' in df_clean.columns:
                status_counts = df_clean['status_code'].value_counts()
                st.bar_chart(status_counts)
            else:
                st.info("Status code information not available.")

            # Detailed Data View
            with st.expander("View Detailed Data"):
                st.dataframe(df_clean)
            
            # Load (Download)
            st.subheader("Export Data")
            csv = df_clean.to_csv(index=False).encode('utf-8')
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