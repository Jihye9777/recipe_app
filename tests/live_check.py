"""Opt-in integration checks; separate temp SQL and unique Weaviate test collection.
Run: python -X utf8 tests/live_check.py --ollama [--weaviate]
Only this run's newly-created test collection is cleaned up.
"""
import argparse
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from domain import normalize, quality, semantic, SearchInput
from integrations import Ollama, WeaviateIndex
from storage import Store

def main():
    p=argparse.ArgumentParser(); p.add_argument('--ollama',action='store_true');p.add_argument('--weaviate',action='store_true');p.add_argument('--workflow',action='store_true')
    args=p.parse_args(); llm=Ollama()
    text='달걀 2개와 청양고추 1개를 프라이팬에 넣어 5분 볶아요. 1인분 요리입니다.'
    if args.workflow:
        from workflows import Pipelines
        collection='RecipeTest'+uuid.uuid4().hex
        os.environ['WEAVIATE_COLLECTION']=collection
        index=WeaviateIndex(llm); indexed=False
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.db')
            graph=Pipelines(store,llm,index,lambda url:('','ko','unused'),str(Path(tmp)/'checkpoints.db'))
            try:
                id=str(uuid.uuid4());graph.run(id,{'text':text})
                job=store.job(id)
                if job['status']=='review':
                    print(json.dumps({'workflow':'review','issues':job['result']['issues']},ensure_ascii=False),flush=True)
                else:
                    assert job['status']=='complete',job
                    indexed=job['result']['recipe']['index_status']=='indexed'
                    assert len(store.all())==1
                    out=graph.search.invoke({'request':{'pantry':['달걀','청양고추']}})['result']
                    assert out['recipes'][0]['coverage']==100,out
                    print(json.dumps({'workflow':'complete','sqlite_saved':True,'weaviate_indexed':indexed,'search_coverage':100,'warnings':out['warnings']},ensure_ascii=False),flush=True)
            finally:
                graph.checkpoint_db.close()
                if indexed:
                    with index.connect() as client:client.collections.delete(collection)
                    print('Removed only the temporary integration-test collection: '+collection,flush=True)
        return
    if args.ollama:
        recipe=normalize(llm.recipe(text)); issues=quality(recipe,text)
        print(json.dumps({'generation':'ok','recipe':recipe,'quality_issues':issues},ensure_ascii=False),flush=True)
        vector=llm.embed(semantic(recipe,text)['search_text'])
        assert vector and all(isinstance(x,(int,float)) for x in vector)
        print(json.dumps({'embedding':'ok','dimensions':len(vector)}),flush=True)
    else:
        recipe=normalize({'title':'통합 검사 레시피','time':5,'ingredients':[{'raw_name':'청양고추','name':'청양고추','evidence':text}],'steps':['볶아요.']})
        vector=llm.embed(semantic(recipe,text)['search_text'])
    if args.weaviate:
        collection='RecipeTest'+uuid.uuid4().hex
        os.environ['WEAVIATE_COLLECTION']=collection
        index=WeaviateIndex(llm)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.db'); rid=str(uuid.uuid4())
            row=store.save(rid,'test:'+rid,'',text,recipe,semantic(recipe,text),llm.model)
            try:
                index.upsert(row,vector);index.upsert(row,vector)
                ids=index.search('매운 요리',SearchInput(min_spice=2))
                assert rid in ids,ids
                with index.connect() as client:
                    assert client.collections.get(collection).aggregate.over_all(total_count=True).total_count==1
                print(json.dumps({'weaviate':'ok','hybrid_hit':True,'idempotent_upsert':True}),flush=True)
            finally:
                with index.connect() as client:
                    if client.collections.exists(collection): client.collections.delete(collection)
                print('Removed only the temporary integration-test collection: '+collection,flush=True)

if __name__=='__main__':main()
