import streamlit as st

st.title("Test App")
st.write("If you can see this, Streamlit works.")

if 'count' not in st.session_state:
    st.session_state.count = 0

if st.button("Click me"):
    st.session_state.count += 1

st.write(f"Button clicked {st.session_state.count} times")