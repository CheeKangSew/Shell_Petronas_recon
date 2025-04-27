import streamlit as st
import pandas as pd
import numpy as np
from io import StringIO

# --- Data Preparation Functions ---
def prepare_soliduz(file, partner='Shell'):
    df = pd.read_csv(file)
    df['Transaction Date'] = pd.to_datetime(df['CreationDate'], format='%d/%m/%Y', errors='coerce')
    df['Transaction Time'] = pd.to_datetime(df['CreationTime'], format='%H:%M:%S', errors='coerce').dt.time
    df = df.dropna(subset=['Transaction Date', 'Transaction Time'])
    df['CreationDateTime'] = pd.to_datetime(df['Transaction Date'].astype(str) + ' ' + df['Transaction Time'].astype(str), errors='coerce')
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce')
    df['VehicleNumber1'] = df['VehicleRegistrationNo'].str.replace(r'\s+', '', regex=True)

    # Filter based on ItemName
    if partner == 'Shell':
        df = df[~df['ItemName'].str.contains('Petronas', case=False, na=False)]
    elif partner == 'Petronas':
        df = df[~df['ItemName'].str.contains('Shell', case=False, na=False)]

    return df

def prepare_shell(file):
    df = pd.read_csv(file)
    df = df[~df['Site Name'].str.contains('DUMMY', case=False, na=False)]
    df['Delivery Date'] = df['Delivery Date'].astype(str).str.strip()
    df['Time'] = df['Time'].astype(str).str.strip()
    df['Transaction Date'] = pd.to_datetime(df['Delivery Date'], format='%d/%m/%Y', errors='coerce')
    df['Transaction Time'] = pd.to_datetime(df['Time'], format='%H:%M:%S', errors='coerce').dt.time
    df = df.dropna(subset=['Transaction Date', 'Transaction Time'])
    df['CreationDateTime'] = pd.to_datetime(df['Transaction Date'].astype(str) + ' ' + df['Transaction Time'].astype(str), errors='coerce')
    df['Amount2'] = pd.to_numeric(df['Net Amount in Customer currency'], errors='coerce')
    df['VehicleNumber2'] = df['Vehicle License Number'].str.replace(r'\s+', '', regex=True)
    return df[['CreationDateTime', 'Amount2', 'VehicleNumber2', 'Site Name', 'Receipt Number']]

def prepare_petronas(file):
    df = pd.read_csv(file)
    df['Date Time'] = pd.to_datetime(df['Date Time'], format='%d/%m/%Y %H:%M', errors='coerce')
    df = df.dropna(subset=['Date Time'])
    df['Transaction Date'] = df['Date Time'].dt.date
    df['Transaction Time'] = df['Date Time'].dt.time
    df['CreationDateTime'] = pd.to_datetime(df['Transaction Date'].astype(str) + ' ' + df['Transaction Time'].astype(str), errors='coerce')
    df['Amount2'] = pd.to_numeric(df['Transaction Amount (RM)'], errors='coerce')
    df['VehicleNumber2'] = df['Vehicle Number'].str.replace(r'\s+', '', regex=True)
    return df[['CreationDateTime', 'Amount2', 'VehicleNumber2', 'Station Name']]

# --- Matching Function ---
def match_transactions(df1, df2, partner='Shell', time_buffer_hours=1):
    time_buffer = pd.Timedelta(hours=time_buffer_hours)
    matched = []

    for index1, row1 in df1.iterrows():
        if partner == 'Shell':
            df2_match = df2[
                (df2['VehicleNumber2'] == row1['VehicleNumber1']) &
                (df2['CreationDateTime'] >= (row1['CreationDateTime'] - time_buffer)) &
                (df2['CreationDateTime'] <= (row1['CreationDateTime'] + time_buffer)) &
                (df2['Site Name'] == row1['PetrolStationName']) &
                (abs(df2['Amount2'] - row1['Amount']) < 0.01)
            ]
        else:
            df2_match = df2[
                (df2['VehicleNumber2'] == row1['VehicleNumber1']) &
                (df2['CreationDateTime'] >= (row1['CreationDateTime'] - time_buffer)) &
                (df2['CreationDateTime'] <= (row1['CreationDateTime'] + time_buffer)) &
                (df2['Station Name'] == row1['PetrolStationName']) &
                (abs(df2['Amount2'] - row1['Amount']) < 0.01)
            ]

        for _, row2 in df2_match.iterrows():
            match_row = row1.to_dict()
            match_row.update(row2.to_dict())
            matched.append(match_row)

    matched_df = pd.DataFrame(matched)
    return matched_df

# --- Mismatch Reason Analysis ---
def find_mismatch_reasons(df1, df2, matched, partner='Shell', time_buffer_hours=1):
    time_buffer = pd.Timedelta(hours=time_buffer_hours)
    mismatched = df1.copy()
    mismatched['MismatchReason'] = ''

    for index1, row1 in mismatched.iterrows():
        if any((matched['CreationDateTime'] == row1['CreationDateTime']) &
               (matched['Amount'] == row1['Amount']) &
               (matched['VehicleNumber1'] == row1['VehicleRegistrationNo']) &
               (matched['PetrolStationName'] == row1['PetrolStationName'])):
            continue

        df2_vehicle_match = df2[df2['VehicleNumber2'] == row1['VehicleNumber1']]
        if df2_vehicle_match.empty:
            mismatched.at[index1, 'MismatchReason'] = 'Vehicle Mismatch'
            continue

        df2_time_match = df2_vehicle_match[
            (df2_vehicle_match['CreationDateTime'] >= (row1['CreationDateTime'] - time_buffer)) &
            (df2_vehicle_match['CreationDateTime'] <= (row1['CreationDateTime'] + time_buffer))
        ]
        if df2_time_match.empty:
            mismatched.at[index1, 'MismatchReason'] = 'Time Mismatch'
            continue

        if partner == 'Shell':
            df2_site_match = df2_time_match[df2_time_match['Site Name'] == row1['PetrolStationName']]
        else:
            df2_site_match = df2_time_match[df2_time_match['Station Name'] == row1['PetrolStationName']]

        if df2_site_match.empty:
            mismatched.at[index1, 'MismatchReason'] = 'Site Name Mismatch'
            continue

        df2_amount_match = df2_site_match[abs(df2_site_match['Amount2'] - row1['Amount']) < 0.01]
        if df2_amount_match.empty:
            mismatched.at[index1, 'MismatchReason'] = 'Amount Mismatch'

    mismatched = mismatched[mismatched['MismatchReason'] != '']
    return mismatched

# --- Streamlit App ---
st.title("Soliduz Transaction Matching App")

with st.sidebar:
    st.header("Upload Files")
    soliduz_file = st.file_uploader("Upload Soliduz file (CSV)", type=["csv"])
    shell_file = st.file_uploader("Upload Shell file (CSV)", type=["csv"])
    petronas_file = st.file_uploader("Upload Petronas file (CSV)", type=["csv"])

    st.header("Matching Options")
    partner = st.radio("Select Partner to Match Against", ("Shell", "Petronas"))
    time_buffer = st.slider("Select Time Buffer (hours)", 0, 24, 1)

if soliduz_file and shell_file and petronas_file:
    # Load Data
    soliduz = prepare_soliduz(soliduz_file, partner)
    shell = prepare_shell(shell_file)
    petronas = prepare_petronas(petronas_file)

    # Select Partner Data
    partner_data = shell if partner == 'Shell' else petronas

    # Match Transactions
    matched = match_transactions(soliduz, partner_data, partner, time_buffer)

    st.success(f"Matching completed against {partner}! ✅")

    # Display Summary
    st.subheader("Summary")
    st.write(f"Total transactions in Soliduz file: {soliduz.shape[0]}")
    st.write(f"Total transactions in {partner} file: {partner_data.shape[0]}")
    st.write(f"Total matched transactions: {matched.shape[0]}")

    st.subheader("Matched Transactions")
    st.dataframe(matched)

    soliduz['Matched'] = soliduz.apply(
        lambda row: any(
            (matched['CreationDateTime'] == row['CreationDateTime']) &
            (matched['Amount'] == row['Amount']) &
            (matched['VehicleNumber1'] == row['VehicleRegistrationNo']) &
            (matched['PetrolStationName'] == row['PetrolStationName'])
        ), axis=1
    )

    st.subheader("Soliduz File with Matched Status")
    st.dataframe(soliduz)

    # Mismatch Analysis
    st.subheader("Mismatch Reason Analysis")
    mismatched = find_mismatch_reasons(soliduz, partner_data, matched, partner, time_buffer)
    st.dataframe(mismatched)

    # Download Buttons
    st.download_button("Download Matched Transactions", matched.to_csv(index=False).encode('utf-8'), "matched_transactions.csv", "text/csv")
    st.download_button("Download Processed Soliduz File", soliduz.to_csv(index=False).encode('utf-8'), "soliduz_processed.csv", "text/csv")
    st.download_button("Download Mismatched Transactions", mismatched.to_csv(index=False).encode('utf-8'), "mismatched_transactions.csv", "text/csv")

else:
    st.warning("Please upload all three files to proceed!")
