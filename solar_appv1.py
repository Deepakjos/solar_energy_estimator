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

# --- STYLING (Revised for Metric Font Size) ---
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    /* Target the metric value and label to fit the box */
    [data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.9rem !important;
        white-space: normal !important;
    }
    .stMetric { 
        background-color: #ffffff; 
        padding: 15px; 
        border-radius: 12px; 
        border: 1px solid #e0e0e0;
        height: 120px;
    }
    div[data-testid="stExpander"] { background-color: white; border-radius: 10px; }
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; background-color: #FF4B4B; color: white; }
    </style>
""", unsafe_allow_html=True)

# --- CACHED LOGIC ---
@st.cache_data(show_spinner=False)
def get_coordinates(address):
    try:
        geolocator = Nominatim(user_agent="solar_planner_v1_deployment")
        location = geolocator.geocode(address, timeout=10)
        return (location.latitude, location.longitude, location.address) if location else (None, None, None)
    except:
        return None, None, None

@st.cache_data(show_spinner=False)
def fetch_archive_data(lat, lon, start_date, end_date):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": start_date, "end_date": end_date,
        "hourly": "shortwave_radiation", "timezone": "auto"
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        return res.json() if res.status_code == 200 else None
    except:
        return None

def calculate_geodesic_area(geojson_geometry):
    s = shape(geojson_geometry)
    geod = pyproj.Geod(ellps="WGS84")
    area, _ = geod.geometry_area_perimeter(s)
    return abs(area)

# --- SIDEBAR ---
st.sidebar.header("🏠 Property Details")
address_input = st.sidebar.text_input("Property Address", "Pune, Maharashtra")
monthly_bill = st.sidebar.number_input("Avg. Monthly Bill (₹)", value=3000, step=500)
electricity_rate = st.sidebar.slider("Electricity Rate (₹/kWh)", 5.0, 15.0, 8.5)

st.sidebar.header("🔌 System Capacity")
sys_capacity = st.sidebar.slider("Proposed System Size (kW)", 1.0, 50.0, 5.0)
sys_efficiency = st.sidebar.slider("System Efficiency (%)", 50, 95, 78) / 100

# --- MAIN PAGE ---
st.title("☀️ Solar Rooftop Self-Assessment")

if address_input:
    lat, lon, full_address = get_coordinates(address_input)
    
    if lat:
        st.info(f"📍 **Analyzing:** {full_address}")
        
        tab_summary, tab_monthly, tab_hourly, tab_area, tab_guide = st.tabs([
            "💰 Financial & Impact", "📅 Monthly Averages", "📈 Hourly Detail", "📏 Rooftop Area", "📖 Guide"
        ])

        with st.spinner("Analyzing solar potential..."):
            # Fetch full year 2023 data for calculations
            data = fetch_archive_data(lat, lon, "2023-01-01", "2023-12-31")
        
        if data and 'hourly' in data:
            df = pd.DataFrame({
                "Timestamp": pd.to_datetime(data['hourly']['time']),
                "ghi": data['hourly']['shortwave_radiation']
            })
            df['production'] = (df['ghi'] / 1000) * sys_capacity * sys_efficiency
            
            # --- TAB 1: FINANCIAL ---
            with tab_summary:
                annual_yield = df['production'].sum()
                monthly_yield = annual_yield / 12
                annual_savings = annual_yield * electricity_rate
                bill_offset = (monthly_yield / (monthly_bill/electricity_rate) * 100)
                
                c1, c2, c3 = st.columns(3)
                # CSS ensures labels and values fit inside these boxes
                c1.metric("Est. Monthly Gen.", f"{monthly_yield:.0f} kWh")
                c2.metric("Annual Savings", f"₹{annual_savings:,.0f}")
                c3.metric("Bill Offset", f"{bill_offset:.1f}%")

                st.subheader("🌍 Environmental Impact")
                co2_saved = (annual_yield * 0.7) / 1000 
                e1, e2 = st.columns(2)
                e1.metric("CO2 Saved", f"{co2_saved:.2f} Tonnes/Yr")
                e2.metric("Trees Equivalent", f"{int(co2_saved * 45)} Trees")

            # --- TAB 2: MONTHLY ---
            with tab_monthly:
                df['MonthName'] = df['Timestamp'].dt.strftime('%b')
                monthly_df = df.groupby(df['Timestamp'].dt.month).agg({'production': 'sum', 'MonthName': 'first'}).sort_index()
                fig_monthly = px.bar(monthly_df, x='MonthName', y='production', color_discrete_sequence=['#FFD700'])
                st.plotly_chart(fig_monthly, use_container_width=True)

            # --- TAB 3: HOURLY DETAIL (Fixes) ---
            with tab_hourly:
                st.subheader("Historical Hourly Production")
                # Default to 1st Jan of the year
                default_start = datetime(2023, 1, 1)
                default_end = datetime(2023, 1, 1)
                
                date_range = st.date_input(
                    "Select Date (Note: Data is historical for 2023)", 
                    [default_start, default_end],
                    min_value=datetime(2023, 1, 1),
                    max_value=datetime(2023, 12, 31)
                )

                if len(date_range) == 2:
                    mask = (df['Timestamp'].dt.date >= date_range[0]) & (df['Timestamp'].dt.date <= date_range[1])
                    filtered_df = df.loc[mask]
                    
                    if not filtered_df.empty:
                        fig_hourly = px.area(filtered_df, x='Timestamp', y='production', color_discrete_sequence=['#FF8C00'])
                        st.plotly_chart(fig_hourly, use_container_width=True)
                    else:
                        st.warning("No data found for the selected range in the 2023 dataset.")

            # --- TAB 4 & 5 (Existing Logic) ---
            with tab_area:
                m = folium.Map(location=[lat, lon], zoom_start=19)
                folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 
                                 attr='Esri', name='Satellite').add_to(m)
                Draw(export=False).add_to(m)
                out = st_folium(m, width=700, height=500)
                if out.get('all_drawings'):
                    geom = out['all_drawings'][-1]['geometry']
                    if geom['type'] == 'Polygon':
                        a = calculate_geodesic_area(geom)
                        st.success(f"Area: {a:.1f} m² | Potential: {a/10:.1f} kW")
            
            with tab_guide:
                st.write("Using 2023 historical GHI data as a baseline for calculations.")
        else:
            st.error("Could not fetch solar data. Please check connection or address.")
