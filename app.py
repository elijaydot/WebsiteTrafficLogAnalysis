import streamlit as st
import pandas as pd
import io
import re

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
                # Use errors='replace' to handle encoding issues (common in older server logs)
                content = file.getvalue().decode("utf-8", errors="replace")
                
                # Regex to extract fields (Supports Combined and Common Log Format)
                # Made Referer and User Agent optional to support NASA CLF logs
                log_pattern = re.compile(
                    r'(?P<ip_address>\S+) \S+ \S+ \[(?P<timestamp>.*?)\] "(?P<method>\S+) (?P<page_visited>\S+) \S+" (?P<status_code>\d{3}) (?P<data_size>\S+)(?: "(?P<referer>.*?)" "(?P<user_agent>.*?)")?'
                )
                
                data = []
                for line in content.splitlines():
                    match = log_pattern.search(line)
                    if match:
                        row = match.groupdict()
                        # Fix timestamp format for Pandas (replace first : with space)
                        # From: 10/Oct/2000:13:55:36 +0000 -> 10/Oct/2000 13:55:36 +0000
                        row['timestamp'] = row['timestamp'].replace(':', ' ', 1)
                        data.append(row)
                
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
        
        # Convert timestamp
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        
        # Drop rows with invalid timestamps
        df = df.dropna(subset=['timestamp'])
        
        # Extract features
        df['hour_of_day'] = df['timestamp'].dt.hour
        
        # Ensure status_code is int
        df['status_code'] = pd.to_numeric(df['status_code'], errors='coerce').fillna(0).astype(int)
        
        # Clean data_size (replace '-' with 0 and convert to numeric)
        if 'data_size' in df.columns:
            df['data_size'] = pd.to_numeric(df['data_size'], errors='coerce').fillna(0)
        
        # Clean referer
        if 'referer' in df.columns:
            df['referer'] = df['referer'].fillna('-')
        
        return df
    except Exception as e:
        st.error(f"Error during transformation: {e}")
        return None

# --- Sidebar / Input ---

st.sidebar.header("Data Input")
uploaded_file = st.sidebar.file_uploader("Upload Log (CSV, LOG, TXT)", type=['csv', 'log', 'txt'])

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
    df_raw = load_data(uploaded_file)

# --- Main Execution ---

if df_raw is not None:
    # Transform
    df_clean = transform_data(df_raw)
    
    if df_clean is not None:
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
        
        # Top Metrics
        st.subheader("Key Metrics")
        col1, col2, col3, col4 = st.columns(4)
        
        total_requests = len(df_clean)
        unique_visitors = df_clean['ip_address'].nunique()
        error_requests = df_clean[df_clean['status_code'] >= 400]
        error_rate = (len(error_requests) / total_requests) * 100 if total_requests > 0 else 0
        
        # Calculate total data transfer if available
        if 'data_size' in df_clean.columns:
            total_data_gb = df_clean['data_size'].sum() / (1024**3) # Convert bytes to GB
        else:
            total_data_gb = 0
        
        col1.metric("Total Requests", total_requests)
        col2.metric("Unique Visitors", unique_visitors)
        col3.metric("Error Rate", f"{error_rate:.2f}%")
        col4.metric("Data Transferred", f"{total_data_gb:.2f} GB")
        
        # Visualizations
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.subheader("Traffic by Hour")
            hourly_traffic = df_clean['hour_of_day'].value_counts().sort_index()
            st.bar_chart(hourly_traffic)
            
        with col_chart2:
            st.subheader("Top 5 Pages")
            top_pages = df_clean['page_visited'].value_counts().head(5)
            st.bar_chart(top_pages)
            
        # New Analysis Sections
        col_chart3, col_chart4 = st.columns(2)
        
        with col_chart3:
            st.subheader("Daily Traffic Trend")
            if 'timestamp' in df_clean.columns:
                daily_traffic = df_clean.set_index('timestamp').resample('D').size()
                st.line_chart(daily_traffic)

        with col_chart4:
            st.subheader("Top 404 Errors (Missing Pages)")
            missing_pages = df_clean[df_clean['status_code'] == 404]['page_visited'].value_counts().head(5)
            st.bar_chart(missing_pages)

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
        status_counts = df_clean['status_code'].value_counts()
        st.bar_chart(status_counts)

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