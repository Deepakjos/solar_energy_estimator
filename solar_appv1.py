import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
import plotly.express as px
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
import pyproj
from shapely.geometry import shape

# --- APP CONFIGURATION ---
st.set_page_config(page_title="Solar Rooftop Planner", page_icon="☀️", layout="wide")

# --- STYLING ---
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.85rem !important; white-space: normal !important; }
    .stMetric { 
        background-color: #ffffff; 
        padding: 15px; 
        border-radius: 12px; 
        border: 1px solid #e0e0e0;
        height: 110px;
    }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 16px; }
    </style>
""", unsafe_allow_html=True)

# --- LOGIC ---
@st.cache_data(show_spinner=False)
def fetch_solar_data(lat, lon, start_date, end_date):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "hourly": "shortwave_radiation", "timezone": "auto"
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            data = res.json()
            df = pd.DataFrame({
                "Timestamp": pd.to_datetime(data['hourly']['time']),
                "ghi": data['hourly']['shortwave_radiation']
            })
            return df
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# --- SIDEBAR ---
st.sidebar.header("🏠 Property Details")
address_input = st.sidebar.text_input("Property Address", "Pune, Maharashtra")
monthly_bill = st.sidebar.number_input("Avg. Monthly Bill (₹)", value=3000, step=500)
electricity_rate = st.sidebar.slider("Electricity Rate (₹/kWh)", 5.0, 15.0, 8.5)

st.sidebar.header("🔌 System Capacity")
sys_capacity = st.sidebar.slider("Proposed System Size (kW)", 1.0, 50.0, 5.0)
sys_efficiency = st.sidebar.slider("System Efficiency (%)", 50, 95, 78) / 100

if address_input:
    geolocator = Nominatim(user_agent="solar_planner_v1")
    location = geolocator.geocode(address_input, timeout=10)
    
    if location:
        lat, lon = location.latitude, location.longitude
        
        # 1. Fetch Baseline (2024 full year) for Financials
        baseline_df = fetch_solar_data(lat, lon, "2024-01-01", "2024-12-31")
        
        # 2. Fetch Recent (Last 14 days to ensure 1 week of overlap)
        today = datetime.now()
        start_recent = (today - timedelta(days=14)).strftime('%Y-%m-%d')
        end_recent = (today - timedelta(days=2)).strftime('%Y-%m-%d') # Archive has ~2 day delay
        recent_df = fetch_solar_data(lat, lon, start_recent, end_recent)

        tab_summary, tab_monthly, tab_hourly, tab_area = st.tabs([
            "💰 Financials", "📅 Monthly", "📈 Hourly Detail", "📏 Area"
        ])

        # --- FINANCIALS ---
        with tab_summary:
            if not baseline_df.empty:
                baseline_df['prod'] = (baseline_df['ghi'] / 1000) * sys_capacity * sys_efficiency
                ann_yield = baseline_df['prod'].sum()
                mon_yield = ann_yield / 12
                ann_savings = ann_yield * electricity_rate
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Est. Monthly Gen.", f"{mon_yield:.0f} kWh")
                c2.metric("Annual Savings", f"₹{ann_savings:,.0f}")
                c3.metric("Bill Offset", f"{(mon_yield / (monthly_bill/electricity_rate) * 100):.1f}%")

        # --- MONTHLY ---
        with tab_monthly:
            if not baseline_df.empty:
                baseline_df['Month'] = baseline_df['Timestamp'].dt.strftime('%b')
                m_df = baseline_df.groupby(baseline_df['Timestamp'].dt.month).agg({'prod':'sum', 'Month':'first'}).sort_index()
                st.plotly_chart(px.bar(m_df, x='Month', y='prod', color_discrete_sequence=['#FFD700']), use_container_width=True)

        # --- HOURLY (REVISED) ---
        with tab_hourly:
            st.subheader("Recent Production Analysis")
            # Default to 7 days ago
            default_date = datetime.now().date() - timedelta(days=7)
            
            selected_date = st.date_input("Pick a Date", value=default_date)
            
            # Fetch specific day if not in the recent cache
            day_df = fetch_solar_data(lat, lon, selected_date.strftime('%Y-%m-%d'), selected_date.strftime('%Y-%m-%d'))
            
            if not day_df.empty:
                day_df['prod'] = (day_df['ghi'] / 1000) * sys_capacity * sys_efficiency
                fig = px.area(day_df, x='Timestamp', y='prod', title=f"Output for {selected_date}", color_discrete_sequence=['#FF8C00'])
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Data for this date is not yet available in the meteorological archive (usually 2-5 days delay).")

        # --- AREA ---
        with tab_area:
            m = folium.Map(location=[lat, lon], zoom_start=19)
            folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 
                             attr='Esri', name='Satellite').add_to(m)
            Draw(export=False).add_to(m)
            st_folium(m, width=700, height=450)

    else:
        st.error("Location not found.")
