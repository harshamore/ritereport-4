import streamlit as st
import pandas as pd
import sqlite3
import os
import openai
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
# Set OpenAI API key from Streamlit secrets
openai.api_key = st.secrets["OPENAI_API_KEY"]

# Database setup
def init_db():
    conn = sqlite3.connect('account_mappings.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS mappings
                 (id INTEGER PRIMARY KEY,
                  input_text TEXT,
                  context TEXT,
                  classification_type TEXT,
                  label_path TEXT,
                  label_code TEXT,
                  reasoning TEXT,
                  ind_as TEXT,
                  confirmed BOOLEAN,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

# Structured labels
LABEL_HIERARCHY = {
    "Balance Sheet": {
        "ASSETS": {
            "(1) Non-current assets": {
                "(a) Property, Plant and Equipment": {},
                "(b) Capital work-in-progress": {},
                "(c) Investment Property": {},
                "(d) Goodwill": {},
                "(e) Other Intangible assets": {},
                "(f) Intangible assets under development": {},
                "(g) Biological Assets other than bearer plants": {},
                "(h) Financial Assets": {
                    "(i) Investments": {},
                    "(ii) Trade receivables": {},
                    "(iii) Loans": {}
                },
                "(i) Deferred assets (net) tax": {},
                "(j) Other noncurrent assets": {}
            },
            "(2) Current assets": {
                "(a) Inventories": {},
                "(b) Financial Assets": {
                    "(i) Investments": {},
                    "(ii) Trade receivables": {},
                    "(iii) Cash and cash equivalents": {},
                    "(iv) Bank balances other than(iii) above": {},
                    "(v) Loans": {},
                    "(vi) Others (to be specified)": {}
                },
                "(c) Current Tax Assets (Net)": {},
                "(d) Other current assets": {}
            }
        },
        "EQUITY": {
            "(a) Equity Share capital": {},
            "(b) Other Equity": {}
        },
        "LIABILITIES": {
            "(1) Non-current liabilities": {
                "(a) Financial Liabilities": {
                    "(i) Borrowings": {},
                    "(ia) Lease liabilities": {},
                    "(ii) Trade Payables": {
                        "(A) micro/small enterprises": {},
                        "(B) other creditors": {}
                    },
                    "(iii) Other financial liabilities": {}
                },
                "(b) Provisions": {},
                "(c) Deferred tax liabilities (Net)": {},
                "(d) Other noncurrent liabilities": {}
            },
            "(2) Current liabilities": {
                "(a) Financial Liabilities": {
                    "(i) Borrowings": {},
                    "(ia) Lease liabilities": {},
                    "(ii) Trade Payables": {
                        "(A) micro/small enterprises": {},
                        "(B) other creditors": {}
                    },
                    "(iii) Other financial liabilities": {}
                },
                "(b) Other current liabilities": {},
                "(c) Provisions": {},
                "(d) Current Tax Liabilities (Net)": {}
            }
        }
    },
    "Profit & Loss": {
        "I Revenue From operations": {},
        "II Other Income": {},
        "IV EXPENSES": {
            "(a) Cost of materials consumed": {},
            "(b) Purchases of Stock-in-Trade": {},
            "(c) Changes in inventories": {},
            "(d) Employee benefits expense": {},
            "(e) Finance costs": {},
            "(f) Depreciation and amortization": {},
            "(g) Other expenses": {}
        },
        "V Profit/(loss) before tax": {},
        "VIII Tax expense": {
            "(1) Current tax": {},
            "(2) Deferred tax": {}
        },
        "XI Profit (Loss) continuing operations": {},
        "XII Profit/(loss) Discontinued operations": {}
    }
}

def get_label_options():
    options = []
    for cls_type, categories in LABEL_HIERARCHY.items():
        for category, subcats in categories.items():
            stack = [(category, subcats, f"{cls_type} > {category}")]
            while stack:
                name, children, path = stack.pop()
                if not children:
                    options.append(f"{path} > {name}")
                else:
                    for child_name, child_children in children.items():
                        new_path = f"{path} > {child_name}"
                        if not child_children:
                            options.append(new_path)
                        else:
                            stack.append((child_name, child_children, new_path))
    return options

LABEL_OPTIONS = get_label_options()

def get_llm_response(text, context):
    system_prompt = f"""You are a senior Indian accountant mapping trial balance items to IND AS labels. 
    Follow these rules:
    1. First determine if Balance Sheet or Profit & Loss
    2. Select EXACTLY ONE label from this structured list:
    {LABEL_OPTIONS}
    3. Follow the hierarchy exactly
    4. Include full label path
    5. Provide brief reasoning with Ind AS reference"""
    
    user_prompt = f"""Account Entry:
    Text: {text}
    Context: {context}
    
    Respond STRICTLY in format:
    Classification Type: [Balance Sheet/Profit & Loss]
    Label Path: [Full hierarchy path]
    Reasoning: [Brief explanation]
    Ind AS: [Standard number]"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        return parse_response(response.choices[0].message.content)
    except Exception as e:
        st.error(f"OpenAI API error: {str(e)}")
        return None

def parse_response(response):
    result = {
        'classification_type': 'Unknown',
        'label_path': 'Unknown',
        'reasoning': 'Unknown',
        'ind_as': 'Unknown'
    }
    
    lines = response.split('\n')
    for line in lines:
        if line.startswith('Classification Type:'):
            result['classification_type'] = line.split(': ')[1].strip()
        elif line.startswith('Label Path:'):
            label_path = line.split(': ')[1].strip()
            result['label_path'] = validate_label_path(label_path)
        elif line.startswith('Reasoning:'):
            result['reasoning'] = line.split(': ')[1].strip()
        elif line.startswith('Ind AS:'):
            result['ind_as'] = line.split(': ')[1].strip()
    
    return result

def validate_label_path(path):
    for option in LABEL_OPTIONS:
        if path in option:
            return option
    return "UNKNOWN LABEL - NEEDS REVIEW"

def check_existing_mapping(text, context):
    conn = sqlite3.connect('account_mappings.db')
    c = conn.cursor()
    c.execute('''SELECT classification_type, label_path, reasoning, ind_as 
                 FROM mappings 
                 WHERE input_text=? AND context=? AND confirmed=1''',
              (text, context))
    result = c.fetchone()
    conn.close()
    return result

def save_mapping(text, context, classification_type, label_path, reasoning, ind_as, confirmed):
    conn = sqlite3.connect('account_mappings.db')
    c = conn.cursor()
    c.execute('''INSERT INTO mappings 
                 (input_text, context, classification_type, label_path, reasoning, ind_as, confirmed)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (text, context, classification_type, label_path, reasoning, ind_as, confirmed))
    conn.commit()
    conn.close()

# Streamlit app
def main():
    st.title("IND AS Account Mapper")
    init_db()

    uploaded_file = st.file_uploader("Upload Trial Balance Excel File", type=['xlsx'])
    
    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file, sheet_name='TrialBalance')
            
            if not all(col in df.columns for col in ['Account Names', 'Credit', 'Debit']):
                st.error("Missing required columns in 'TrialBalance' sheet")
                return
            
            results = []
            
            for index, row in df.iterrows():
                account_name = row['Account Names']
                context = 'Credit' if pd.notnull(row['Credit']) else 'Debit' if pd.notnull(row['Debit']) else None
                
                if not context or pd.isnull(account_name):
                    continue
                
                existing = check_existing_mapping(account_name, context)
                
                if existing:
                    results.append({
                        'Account Name': account_name,
                        'Context': context,
                        'Classification': existing[0],
                        'Label Path': existing[1],
                        'Source': 'Database',
                        'Confirmed': 'Yes'
                    })
                else:
                    llm_response = get_llm_response(account_name, context)
                    
                    if not llm_response:
                        continue
                        
                    with st.expander(f"Verify: {account_name}"):
                        st.write(f"**Context:** {context}")
                        
                        cols = st.columns(2)
                        cols[0].write(f"**Classification:** {llm_response['classification_type']}")
                        cols[1].write(f"**Ind AS:** {llm_response['ind_as']}")
                        
                        st.write(f"**Label Path:**")
                        st.code(llm_response['label_path'])
                        
                        st.write(f"**Reasoning:** {llm_response['reasoning']}")
                        
                        confirm = st.radio(
                            "Confirm this mapping?",
                            ("Yes", "No"),
                            key=f"confirm_{index}"
                        )
                        
                        if confirm == "Yes":
                            save_mapping(
                                account_name, context,
                                llm_response['classification_type'],
                                llm_response['label_path'],
                                llm_response['reasoning'],
                                llm_response['ind_as'],
                                True
                            )
                            status = 'Yes'
                        else:
                            status = 'No'
                            save_mapping(
                                account_name, context,
                                llm_response['classification_type'],
                                llm_response['label_path'],
                                llm_response['reasoning'],
                                llm_response['ind_as'],
                                False
                            )
                        
                        results.append({
                            'Account Name': account_name,
                            'Context': context,
                            'Classification': llm_response['classification_type'],
                            'Label Path': llm_response['label_path'],
                            'Source': 'OpenAI',
                            'Confirmed': status
                        })
            
            st.subheader("Mapping Results")
            results_df = pd.DataFrame(results)
            st.dataframe(results_df)
            
            if st.button("Export Results to CSV"):
                results_df.to_csv('mapping_results.csv', index=False)
                st.success("Exported successfully!")
                
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")

if __name__ == "__main__":
    main()
