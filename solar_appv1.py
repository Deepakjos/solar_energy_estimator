import streamlit as st
import requests
import pandas as pd
from datetime import datetime
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
    .main { background-color: #f0f2f6; }
    .stMetric { background-color: #ffffff; padding: 20px; border-radius: 12px; border: 1px solid #e0e0e0; }
    div[data-testid="stExpander"] { background-color: white; border-radius: 10px; }
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; background-color: #FF4B4B; color: white; }
    </style>
""", unsafe_allow_html=True)

# --- REFACTORED LOGIC ---

@st.cache_data(show_spinner=False)
def get_coordinates(address):
    try:
        # Added a more unique user agent to avoid rate limiting on Cloud
        geolocator = Nominatim(user_agent="solar_planner_v1_deployment")
        location = geolocator.geocode(address, timeout=10)
        return (location.latitude, location.longitude, location.address) if location else (None, None, None)
    except Exception as e:
        st.error(f"Geocoding Error: {e}")
        return None, None, None

@st.cache_data(show_spinner=False)
def fetch_archive_data(lat, lon, start_date, end_date):
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "shortwave_radiation",
        "timezone": "auto"
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        res.raise_for_status() # Raise error for 4xx/5xx responses
        return res.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Weather Data Error: {e}")
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
        
        # Tabs
        tab_summary, tab_monthly, tab_hourly, tab_area, tab_guide = st.tabs([
            "💰 Financial & Impact", "📅 Monthly Averages", 
            "📈 Hourly Detail", "📏 Rooftop Area", "📖 Guide"
        ])

        with st.spinner("Fetching 2023 Solar Irradiance data..."):
            # Ensure the year is fully finalized in the archive
            data = fetch_archive_data(lat, lon, "2023-01-01", "2023-12-31")
        
        if data and 'hourly' in data:
            df = pd.DataFrame({
                "Timestamp": pd.to_datetime(data['hourly']['time']),
                "ghi": data['hourly']['shortwave_radiation']
            })
            
            # Clean data (handle NaNs if any)
            df['ghi'] = df['ghi'].fillna(0)
            df['production'] = (df['ghi'] / 1000) * sys_capacity * sys_efficiency
            
            # --- TAB 1: FINANCIAL ---
            with tab_summary:
                annual_yield = df['production'].sum()
                monthly_yield = annual_yield / 12
                annual_savings = annual_yield * electricity_rate
                bill_offset = (monthly_yield / (monthly_bill/electricity_rate) * 100)
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Est. Monthly Generation", f"{monthly_yield:.0f} Units")
                c2.metric("Annual Bill Savings", f"₹{annual_savings:,.0f}")
                c3.metric("Bill Offset", f"{bill_offset:.1f}%")

                st.divider()
                st.subheader("🌍 Environmental Impact")
                co2_saved = (annual_yield * 0.7) / 1000 
                e1, e2 = st.columns(2)
                e1.metric("CO2 Saved", f"{co2_saved:.2f} Tonnes/Yr")
                e2.metric("Tree Equivalent", f"{int(co2_saved * 45)} Trees")

            # --- TAB 2: MONTHLY ---
            with tab_monthly:
                df['Month'] = df['Timestamp'].dt.strftime('%b')
                monthly_df = df.groupby(df['Timestamp'].dt.month).agg({
                    'production': 'sum', 'Month': 'first'
                }).sort_index()
                
                fig_monthly = px.bar(monthly_df, x='Month', y='production', 
                                    title="Energy Yield by Month",
                                    color_discrete_sequence=['#FFD700'])
                st.plotly_chart(fig_monthly, use_container_width=True)

            # --- TAB 3: HOURLY ---
            with tab_hourly:
                date_range = st.date_input("Filter Data Range", [datetime(2023, 4, 1), datetime(2023, 4, 7)])
                if len(date_range) == 2:
                    mask = (df['Timestamp'].dt.date >= date_range[0]) & (df['Timestamp'].dt.date <= date_range[1])
                    fig_hourly = px.area(df.loc[mask], x='Timestamp', y='production', 
                                        color_discrete_sequence=['#FF8C00'])
                    st.plotly_chart(fig_hourly, use_container_width=True)

            # --- TAB 4: AREA ---
            with tab_area:
                m = folium.Map(location=[lat, lon], zoom_start=19)
                folium.TileLayer(
                    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                    attr='Esri', name='Satellite'
                ).add_to(m)
                Draw(export=False, position='topleft').add_to(m)
                
                output = st_folium(m, width=700, height=500)
                if output.get('all_drawings'):
                    geom = output['all_drawings'][-1]['geometry']
                    if geom['type'] == 'Polygon':
                        area_m2 = calculate_geodesic_area(geom)
                        st.success(f"Area: {area_m2:.1f} m² | Est. Capacity: {area_m2/10:.1f} kW")

            with tab_guide:
                st.markdown("### How it Works\n1. Uses historical GHI data.\n2. 78% efficiency assumed.")
        else:
            st.warning("⚠️ No solar data could be retrieved for this location. The API might be restricted or the year range is invalid.")
    else:
        st.error("Address not found. Please be more specific (e.g., add City, State).")
