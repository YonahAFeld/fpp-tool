# app.py
import os
import tempfile
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Company and Facility Lookup", page_icon="🔎", layout="centered")

# --- Configuration ---
CSV_PATH = "companies.csv"        # Path to your CSV file
SEARCH_COL_NAME = "Company"       # Column to search against (case-insensitive)

# Columns to display / edit (and their order)
DESIRED_COLS = [
    "CLASS", "Assignment", "Company", "Address", "City",
    "state", "zip", "Sq Ft", "Industry", "Notes", "Operator", "Utility"
]

# --- Utilities ---
def atomic_write_csv(path: str, df: pd.DataFrame) -> None:
    """
    Write CSV atomically to reduce the chance of a partially-written file.
    """
    dirpath = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix="tmp-", suffix=".csv", dir=dirpath)
    os.close(fd)
    try:
        df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, path)  # atomic on same filesystem
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

def ensure_columns(df: pd.DataFrame, want_display_cols: list, col_map: dict) -> tuple[pd.DataFrame, dict]:
    """
    Ensure all desired columns exist in the DataFrame.
    If a desired column is missing, create it with that exact display name.
    Returns updated df and updated col_map.
    """
    for display in want_display_cols:
        key = display.lower()
        if key not in col_map:
            df[display] = ""
            col_map[display.lower()] = display
    return df, col_map

# --- Data Loading & Column Resolution ---
@st.cache_data(show_spinner=False)
def load_data(path: str):
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except FileNotFoundError:
        st.error(f"CSV not found at '{path}'. Update CSV_PATH or place the file there.")
        st.stop()

    # Map lowercased names -> actual column names (for case-insensitive matching)
    col_map = {c.lower(): c for c in df.columns}

    # Resolve search column
    if SEARCH_COL_NAME.lower() not in col_map:
        st.error(f"Could not find the '{SEARCH_COL_NAME}' column in the CSV.")
        st.stop()
    search_col_actual = col_map[SEARCH_COL_NAME.lower()]

    # Resolve desired columns (case-insensitive), but display with the exact names from DESIRED_COLS
    resolved_cols = []
    rename_map = {}
    missing = []
    for display_name in DESIRED_COLS:
        key = display_name.lower()
        if key in col_map:
            actual = col_map[key]
            resolved_cols.append(actual)
            if actual != display_name:
                rename_map[actual] = display_name  # rename only for display
        else:
            missing.append(display_name)

    # Also build a display->actual map (for editing)
    display_to_actual = {d: col_map.get(d.lower(), d) for d in DESIRED_COLS}

    return df, search_col_actual, resolved_cols, rename_map, missing, col_map, display_to_actual

df, SEARCH_COL, RESOLVED_COLS, RENAME_MAP, MISSING, COL_MAP, DISPLAY_TO_ACTUAL = load_data(CSV_PATH)

# --- UI ---
st.title("🔎 Company and Facility Lookup (CSV)")
st.caption("Search by company name. Pick a record to edit, or add a new one. Changes are saved to the CSV.")

c1, c2 = st.columns([3, 1])
with c1:
    query = st.text_input("Company", placeholder="e.g., Ford Motor Company")
with c2:
    mode = st.radio("Mode", ["Exact", "Contains"], index=0)

if MISSING:
    st.warning(
        "These columns weren't found in your CSV and won't be shown until you save a change (then they'll be created): "
        + ", ".join(MISSING)
    )

# --- Search ---
if not query:
    st.info("Start typing to search…")
    st.stop()

q = query.strip()
if mode == "Exact":
    mask = df[SEARCH_COL].str.strip().str.casefold() == q.casefold()
else:
    mask = df[SEARCH_COL].str.contains(q, case=False, na=False)

results = df.loc[mask]

# Prepare a view limited to desired columns (for display)
view = (
    results[RESOLVED_COLS].rename(columns=RENAME_MAP)
    if RESOLVED_COLS else results
)

def label_for_dropdown(idx: int) -> str:
    # Prefer the cleaned/renamed 'view' (has display names)
    row = (view.loc[idx] if idx in view.index else results.loc[idx])
    def g(r, *names):
        for n in names:
            if n in r.index:
                return str(r.get(n, "")).strip()
        return ""
    addr = g(row, "Address", "address")
    city = g(row, "City", "city")
    state = g(row, "state", "State")
    industry = g(row, "Industry", "industry")
    label = " ".join(x for x in [addr, city, state, industry] if x)
    if not label:
        # Fallback to company name or row id
        label = g(row, "Company", SEARCH_COL) or f"Row {idx}"
    return label

# --- Results / Selection ---
if results.empty:
    st.warning("No matches found.")
else:
    if len(results) == 1:
        st.success("1 match found")
        chosen_idx = results.index[0]
    else:
        st.success(f"{len(results)} matches found")
        idx_options = list(results.index)
        chosen_idx = st.selectbox(
            "Choose a record",
            options=idx_options,
            format_func=label_for_dropdown,
            index=0
        )

    # Show chosen record (pretty key/value)
    chosen_display = (
        df.loc[[chosen_idx], RESOLVED_COLS].rename(columns=RENAME_MAP)
        if RESOLVED_COLS else df.loc[[chosen_idx]]
    )
    st.subheader("Selected record")
    st.table(chosen_display.reset_index(drop=True).T.rename(columns={0: "Value"}))

    # --- Edit Form ---
    st.subheader("Edit this record")
    with st.form(key=f"edit_{chosen_idx}"):
        # Make sure all desired columns exist (for editing). We'll add missing ones on save.
        inputs = {}
        for display_name in DESIRED_COLS:
            actual_col = DISPLAY_TO_ACTUAL.get(display_name, display_name)
            current_val = ""
            if actual_col in df.columns:
                current_val = str(df.loc[chosen_idx, actual_col])
            # Use text_input for all to preserve exact CSV content
            inputs[display_name] = st.text_input(display_name, value=current_val)

        save_edit = st.form_submit_button("Save changes")
        if save_edit:
            # Clear cache and reload fresh to avoid stale writes
            st.cache_data.clear()
            df_fresh, _, _, _, _, col_map_fresh, _ = load_data(CSV_PATH)

            # Ensure all desired columns exist before writing
            df_fresh, col_map_fresh = ensure_columns(df_fresh, DESIRED_COLS, col_map_fresh)

            # Compute display->actual on the fresh map
            display_to_actual_fresh = {d: col_map_fresh.get(d.lower(), d) for d in DESIRED_COLS}

            # If chosen index no longer exists (edge case), stop
            if chosen_idx not in df_fresh.index:
                st.error("Record no longer exists or CSV changed. Please search again.")
                st.stop()

            # Apply updates
            for display_name, new_val in inputs.items():
                actual_col = display_to_actual_fresh[display_name]
                if actual_col not in df_fresh.columns:
                    df_fresh[actual_col] = ""
                df_fresh.loc[chosen_idx, actual_col] = new_val

            # Write atomically
            atomic_write_csv(CSV_PATH, df_fresh)

            st.success("Saved changes to CSV.")
            st.cache_data.clear()
            st.rerun()

# --- Add New Record ---
st.markdown("---")
st.subheader("Add a new record")
with st.form("create_form"):
    create_inputs = {}
    for display_name in DESIRED_COLS:
        # Pre-fill Company with the current query for convenience
        default_val = q if display_name == "Company" and q else ""
        create_inputs[display_name] = st.text_input(display_name, value=default_val)

    enforce_unique = st.checkbox("Require unique Company name (case-insensitive)", value=True)
    create = st.form_submit_button("Create record")

    if create:
        st.cache_data.clear()
        df_fresh, search_col_fresh, _, _, _, col_map_fresh, _ = load_data(CSV_PATH)

        # Ensure columns exist
        df_fresh, col_map_fresh = ensure_columns(df_fresh, DESIRED_COLS, col_map_fresh)
        display_to_actual_fresh = {d: col_map_fresh.get(d.lower(), d) for d in DESIRED_COLS}

        # Uniqueness check (optional)
        new_company = (create_inputs.get("Company") or "").strip()
        if enforce_unique and new_company:
            dup_mask = df_fresh[search_col_fresh].str.strip().str.casefold() == new_company.casefold()
            if dup_mask.any():
                st.error("A record with that Company already exists. Disable the checkbox to allow duplicates.")
                st.stop()

        # Build new row with all columns in df_fresh (preserve other, non-DESIRED columns as blanks)
        new_row = {col: "" for col in df_fresh.columns}
        for display_name, val in create_inputs.items():
            actual_col = display_to_actual_fresh[display_name]
            new_row[actual_col] = val

        df_fresh = pd.concat([df_fresh, pd.DataFrame([new_row])], ignore_index=True)

        atomic_write_csv(CSV_PATH, df_fresh)

        st.success("New record added to CSV.")
        st.cache_data.clear()
        st.rerun()
