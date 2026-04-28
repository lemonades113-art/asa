import sys, time, traceback, numpy as np
import faiss as _faiss
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from langchain_huggingface import HuggingFaceEmbeddings
from lib import load_tushare_docs
import jieba

docs = load_tushare_docs()[0]
emb = HuggingFaceEmbeddings(
    model_name='BAAI/bge-small-zh-v1.5',
    encode_kwargs={'normalize_embeddings': True}
)

# build same texts as _prepare_data
texts = []
chunk_meta = []
for _, row in docs.iterrows():
    api_title = str(row['TITLE'])
    src_content = str(row['SRC_CONTENT'])
    texts.append(f'{api_title}\n{src_content}')
    chunk_meta.append({'type': 'interface'})
    in_output = False
    for line in src_content.splitlines():
        stripped = line.strip()
        if '\u8f93\u51fa\u53c2\u6570' in stripped:
            in_output = True; continue
        if not in_output: continue
        if '|' in stripped:
            clean = stripped.strip('|').strip()
            parts = [p.strip() for p in clean.split('|') if p.strip()]
            if len(parts) >= 3 and parts[1] in ('str','float','int','double','bigint','date'):
                texts.append(f'{api_title} \u5b57\u6bb5: {parts[0]} ({parts[1]}) - {parts[-1]}')
                chunk_meta.append({'type': 'field'})

print(f'Total texts: {len(texts)}')
print(f'Max text len: {max(len(t) for t in texts)}')
print(f'Avg text len: {sum(len(t) for t in texts)//len(texts)}')

print('Starting embed_documents...')
t0 = time.time()
try:
    raw_embs = emb.embed_documents(texts)
    embs = np.array(raw_embs, dtype='float32')
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-9, norms)
    embs = embs / norms
    dim = embs.shape[1]
    idx = _faiss.IndexFlatIP(dim)
    idx.add(embs)
    print(f'FAISS OK: {idx.ntotal} vectors, dim={dim}, took {time.time()-t0:.1f}s')
except Exception as e:
    print(f'FAILED after {time.time()-t0:.1f}s')
    traceback.print_exc()
