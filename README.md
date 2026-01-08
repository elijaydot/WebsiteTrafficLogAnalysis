# Website Traffic Log Analysis

A robust Data Engineering project that demonstrates **ETL (Extract, Transform, Load)** processes on website traffic logs. This project includes a Jupyter Notebook for educational walkthroughs and a live interactive **Streamlit** dashboard for real-time log analysis.

## 🚀 Features

*   **Multi-Format Support**: Upload standard **CSV** files or raw **Apache/Nginx Access Logs** (`.log`, `.txt`).
*   **Automated ETL Pipeline**:
    *   **Extract**: Reads raw text or CSV data.
    *   **Transform**: Parses complex log strings using Regex, cleans timestamps, handles missing values, and calculates data size.
    *   **Load**: Exports processed data to CSV.
*   **Interactive Dashboard**:
    *   **Key Metrics**: Total requests, unique visitors, error rates, and total data transferred (GB).
    *   **Traffic Analysis**: Visualize traffic by hour of day and daily trends over time.
    *   **Content Insights**: Identify top visited pages and top referring websites.
    *   **Issue Detection**: Spot top 404 (Missing Page) errors.
    *   **Security & Bandwidth**: Detect potential image hotlinking from external domains.
*   **Filtering**: Filter analysis by specific date ranges.

## 📂 Project Structure

*   `app.py`: The main entry point for the Streamlit web application. Contains the logic for the dashboard and log parsing.
*   `website_traffic_analysis.ipynb`: A Jupyter Notebook serving as a prototyping environment. It breaks down the logic step-by-step for learning purposes.
*   `requirements.txt`: List of Python dependencies required to run the project.

## 🛠️ Installation

1.  **Prerequisites**: Ensure you have Python 3.7+ installed.

2.  **Install Dependencies**:
    Open your terminal or command prompt in the project directory and run:
    ```bash
    pip install -r requirements.txt
    ```

## 📊 Usage

### Running the Web Application
To launch the interactive dashboard:

```bash
streamlit run app.py
```

Once running, a local URL (usually `http://localhost:8501`) will open in your browser. You can upload your log files directly via the sidebar.

### Running the Notebook
To explore the code logic and step-by-step analysis:
1.  Open the notebook in VS Code or Jupyter Lab:
    ```bash
    jupyter notebook website_traffic_analysis.ipynb
    ```
2.  Run the cells sequentially to see how data is loaded, cleaned, and analyzed.

## 📝 Data Format Support

### 1. CSV Format
If uploading a CSV, it should contain the following headers:
`timestamp`, `ip_address`, `page_visited`, `status_code`, `user_agent`

### 2. Apache/Nginx Log Format
The app supports the **Combined Log Format** and **Common Log Format**.
Example:
```text
127.0.0.1 - - [10/Oct/2023:13:55:36 +0000] "GET /home HTTP/1.1" 200 2326 "http://google.com" "Mozilla/5.0..."
```

## 🔍 Analysis Breakdown

1.  **Unique Visitors**: Counted based on unique IP addresses.
2.  **Error Rate**: Percentage of requests returning 4xx or 5xx status codes.
3.  **Hotlinking**: Identifies external domains (Referers) requesting image files (png, jpg, etc.) from your server.
4.  **Bandwidth**: Sums up the size of data transferred in responses.

## 📜 License

This project is open-source and available for educational purposes.