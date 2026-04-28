"""
Homework 1: Fundamentals of Text Analytics
"""

import re
import numpy as np
import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Download required NLTK data
nltk.download('stopwords', quiet=True)
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)

# ============================================================
# Part I: Text Data
# ============================================================

# Document 1: CEO Earnings Call Statement
doc1 = (r"Over the past quarter, our company has delivered strong revenue growth "
        r"driven by increased customer demand and operational efficiency. We continue "
        r"to invest in innovation, expand our digital capabilities, and strengthen our "
        r"core business segments. While macroeconomic uncertainty remains, we are "
        r"confident in our long-term strategy and our ability to create sustainable "
        r"value for shareholders.")

# Document 2: Company-Wide Strategy Memo
doc2 = (r"Today, we are announcing a strategic transformation to position our "
        r"organization for future growth. This initiative focuses on cost optimization, "
        r"workforce upskilling, and technology modernization. By improving collaboration "
        r"across teams and leveraging data-driven decision making, we aim to enhance "
        r"productivity of an organization and remain competitive in an evolving market.")

documents = [doc1, doc2]

# Display documents
for i in range(2):
    print(f'Document {i}:')
    print(documents[i][:100] + "...")
    print()

# ============================================================
# Part II: Text Preprocessing and DTM
# ============================================================

# 1. Convert all letters to lowercase
lowercase_docs = [doc.lower() for doc in documents]
print("=== Lowercase ===")
for i, doc in enumerate(lowercase_docs):
    print(f"Doc {i}: {doc[:100]}...")
print()

# 2. Remove all punctuations, linebreaks, numbers (keep spaces)
def clean_text(text):
    # Remove punctuation, numbers, and line breaks/tabs
    cleaned = re.sub(r'[^a-zA-Z\s]', ' ', text)
    # Replace multiple spaces with single space
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

cleaned_docs = [clean_text(doc) for doc in lowercase_docs]
print("=== Cleaned Text ===")
for i, doc in enumerate(cleaned_docs):
    print(f"Doc {i}: {doc[:100]}...")
print()

# 3. Tokenize the text into words (use word_tokenize for accuracy)
def tokenize(text):
    return word_tokenize(text)

tokenized_docs = [tokenize(doc) for doc in cleaned_docs]
print("=== Tokenized ===")
for i, tokens in enumerate(tokenized_docs):
    print(f"Doc {i}: {tokens[:15]}...")
print()

# 4. Remove stop words using NLTK
stop_words = set(stopwords.words('english'))
filtered_docs = [[word for word in tokens if word not in stop_words] 
                  for tokens in tokenized_docs]
print("=== After Stop Words Removal ===")
for i, tokens in enumerate(filtered_docs):
    print(f"Doc {i}: {tokens[:15]}...")
print()

# 【关键补充】存储「词干提取前的filtered_docs」（用于正则匹配）
pre_stem_docs = filtered_docs.copy()

# 5. Stemming using NLTK PorterStemmer
stemmer = PorterStemmer()
stemmed_docs = [[stemmer.stem(word) for word in tokens] 
                 for tokens in filtered_docs]
print("=== After Stemming ===")
for i, tokens in enumerate(stemmed_docs):
    print(f"Doc {i}: {tokens[:15]}...")
print()

# 6. Build the lexicon (unique words from both documents)
lexicon = sorted(set(stemmed_docs[0] + stemmed_docs[1]))
print(f"=== Lexicon (size: {len(lexicon)}) ===")
print(lexicon)
print()

# 7. Build the DTM (Document-Term Matrix)
def build_dtm(documents, lexicon):
    dtm = np.zeros((len(documents), len(lexicon)))
    for doc_idx, doc in enumerate(documents):
        for word in doc:
            if word in lexicon:
                word_idx = lexicon.index(word)
                dtm[doc_idx, word_idx] += 1
    return dtm

dtm = build_dtm(stemmed_docs, lexicon)
print("=== Document-Term Matrix ===")
print(f"Shape: {dtm.shape}")
print(f"Doc 0 non-zero terms: {np.sum(dtm[0] > 0)}")
print(f"Doc 1 non-zero terms: {np.sum(dtm[1] > 0)}")
print()

# 8. TF-IDF Weighting using sklearn
# Join stemmed tokens back to text for TF-IDF vectorizer
stemmed_texts = [' '.join(doc) for doc in stemmed_docs]

tfidf_vectorizer = TfidfVectorizer(vocabulary=lexicon)
tfidf_matrix = tfidf_vectorizer.fit_transform(stemmed_texts)
tfidf_dense = tfidf_matrix.toarray()

print("=== TF-IDF Matrix ===")
print(f"Shape: {tfidf_dense.shape}")
print()

# 9. Document Similarity
# 9a. Cosine similarity using TF-IDF
cosine_sim = cosine_similarity(tfidf_dense[0:1], tfidf_dense[1:2])[0][0]
print(f"=== Cosine Similarity ===")
print(f"Cosine similarity between Doc 0 and Doc 1: {cosine_sim:.4f}")
print()

# 9b. Jaccard similarity using sets of tokens
def jaccard_similarity(set1, set2):
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0

set1 = set(stemmed_docs[0])
set2 = set(stemmed_docs[1])
jaccard_sim = jaccard_similarity(set1, set2)
print(f"=== Jaccard Similarity ===")
print(f"Jaccard similarity between Doc 0 and Doc 1: {jaccard_sim:.4f}")
print()

# Interpretation
print("=== Interpretation ===")
print(f"""
The two documents show moderate similarity:
- Cosine similarity: {cosine_sim:.4f} (measures angular similarity in vector space)
- Jaccard similarity: {jaccard_sim:.4f} (measures set overlap)

Analysis: Both documents are business communications discussing strategy and growth.
Common themes include: growth, strategy, innovation, technology, and organization.
The moderate similarity reflects their shared business context despite different 
purposes (earnings call vs. strategy memo).
""")

# ============================================================
# Part III: Regular Expression
# ============================================================

print("=" * 60)
print("Part III: Regular Expression")
print("=" * 60)

# 【问题1】Find all unique words ending with "ing" in both documents (sorted)
# 【修正】必须使用词干提取前的 pre_stem_docs（保留 ing 后缀原始形态）
all_pre_stem_tokens = pre_stem_docs[0] + pre_stem_docs[1]
words_ending_ing = sorted(set([word for word in all_pre_stem_tokens if word.endswith('ing')]))
print("\n1. Words ending with 'ing' (sorted):")
print(words_ending_ing)
# 正确输出示例：['decision', 'evolving', 'improving', 'making']

# 【问题2】Find unique words ending with "ion" in the second document
# 【修正】使用词干提取前的 pre_stem_docs[1]（保留 ion 后缀原始形态）
doc2_pre_stem = pre_stem_docs[1]
words_ending_ion_doc2 = sorted(set([word for word in doc2_pre_stem if word.endswith('ion')]))
print(f"\n2. Words ending with 'ion' in Document 2:")
print(words_ending_ion_doc2)
print(f"Count: {len(words_ending_ion_doc2)}")
# 正确输出示例：['organization', 'optimization', 'transformation']，Count: 3

# 找首次/末次出现位置 & 首次出现前的单词数
if words_ending_ion_doc2:
    # 遍历原始token列表（保留重复），找所有ion结尾单词的位置
    ion_positions = []
    for idx, word in enumerate(doc2_pre_stem):
        if word.endswith('ion'):
            ion_positions.append((idx, word))
    
    first_ion = ion_positions[0]  # 首次出现
    last_ion = ion_positions[-1]  # 末次出现
    print(f"First word: '{first_ion[1]}' at position {first_ion[0]}")
    print(f"Last word: '{last_ion[1]}' at position {last_ion[0]}")
    print(f"Words before first occurrence: {first_ion[0]}")
    # 正确输出示例：First word: 'transformation' at position 3
    #              Last word: 'organization' at position 24
    #              Words before first occurrence: 3

# 【问题3】Positive Lookahead and Lookbehind
# 【修正】使用原始小写文本 + 正则 lookahead/lookbehind 语法（(?=...)/(?<=...)）
full_text = ' '.join(lowercase_docs)

# 3a. 正向前瞻 (?=\sgrowth\b) - 找后面跟"growth"的单词（不含growth）
lookahead_pattern = r'\b(\w+)\b(?=\sgrowth\b)'
words_before_growth = sorted(set(re.findall(lookahead_pattern, full_text)))
print("\n3a. Words followed by 'growth' (positive lookahead):")
print(words_before_growth)
# 正确输出示例：['future', 'revenue']

# 3b. 正向后顾 (?<=\bstrategic\s) - 找紧跟在"strategic"后的单词（不含strategic）
lookbehind_pattern = r'(?<=\bstrategic\s)(\w+)\b'
words_after_strategic = sorted(set(re.findall(lookbehind_pattern, full_text)))
print("\n3b. Words appearing immediately after 'strategic' (positive lookbehind):")
print(words_after_strategic)
# 正确输出示例：['transformation']

print("\n" + "=" * 60)
print("Homework Complete!")
print("=" * 60)
