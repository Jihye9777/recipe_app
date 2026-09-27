"""Opt-in integration checks using temporary SQLite and Qdrant Local folders.
Run: python -X utf8 tests/live_check.py --ollama [--qdrant] [--workflow]
"""
import argparse
import json
import sys
import tempfile
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from domain import normalize, quality, semantic, SearchInput
from integrations import Ollama, QdrantIndex
from storage import Store

def fixture_recipe():
    return normalize({'title':'통합 검사 레시피','time':5,
        'ingredients':[{'raw_name':'청양고추','name':'청양고추','evidence':'청양고추 1개'}],
        'steps':['청양고추 1개를 볶아요.']})

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--ollama',action='store_true')
    parser.add_argument('--qdrant',action='store_true')
    parser.add_argument('--workflow',action='store_true')
    args=parser.parse_args(); llm=Ollama()
    text='달걀 2개와 청양고추 1개를 프라이팬에 넣어 5분 볶아요. 1인분 요리입니다.'
    recipe=fixture_recipe()
    if args.ollama or args.workflow:
        recipe=normalize(llm.recipe(text)); issues=quality(recipe,text)
        print(json.dumps({'generation':'ok','recipe':recipe,'quality_issues':issues},ensure_ascii=False),flush=True)
        vector=llm.embed(semantic(recipe,text)['search_text'])
        assert vector and all(isinstance(x,(int,float)) for x in vector)
        print(json.dumps({'embedding':'ok','dimensions':len(vector)}),flush=True)
    else: vector=llm.embed(semantic(recipe,text)['search_text'])
    if args.workflow:
        from workflows import Pipelines
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Store(root/'recipe.db');index=QdrantIndex(llm,root/'qdrant')
            graph=Pipelines(store,llm,index,lambda url:('','ko','unused'),str(root/'checkpoints.db'))
            try:
                id=str(uuid.uuid4());graph.run(id,{'text':text});job=store.job(id)
                if job['status']=='review':
                    print(json.dumps({'workflow':'review','issues':job['result']['issues']},ensure_ascii=False),flush=True)
                else:
                    assert job['status']=='complete',job
                    assert job['result']['recipe']['index_status']=='indexed',job
                    out=graph.search.invoke({'request':{'pantry':['달걀','청양고추']}})['result']
                    assert out['recipes'][0]['coverage']==100,out
                    print(json.dumps({'workflow':'complete','sqlite_saved':True,'qdrant_indexed':True,
                        'search_coverage':100,'warnings':out['warnings']},ensure_ascii=False),flush=True)
            finally:graph.checkpoint_db.close();index.close()
        return
    if args.qdrant:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Store(root/'recipe.db');index=QdrantIndex(llm,root/'qdrant')
            rid=str(uuid.uuid4());row=store.save(rid,'test:'+rid,'',text,recipe,semantic(recipe,text),llm.model)
            try:
                index.upsert(row,vector);index.upsert(row,vector)
                ids=index.search('매운 요리',SearchInput(min_spice=2))
                assert rid in ids,ids
                assert index.health()['vectors']==1
                print(json.dumps({'qdrant_local':'ok','semantic_hit':True,'idempotent_upsert':True,
                    'storage_path':str(root/'qdrant')},ensure_ascii=False),flush=True)
            finally:index.close()

if __name__=='__main__':main()
