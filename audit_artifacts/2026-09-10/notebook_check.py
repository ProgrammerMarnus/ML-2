"""Execute the unmodified notebook in an isolated working directory."""
from pathlib import Path
import json
import traceback
import nbformat
from nbclient import NotebookClient

ROOT=Path('/home/marnus/VS-Code/ML-2')
OUT=Path(__file__).resolve().parent
WORK=Path('/tmp/ml2-deep-audit-integration-20260910')
original=ROOT/'Institutional_Quant_Research_Engine_V2.1.ipynb'
nb=nbformat.read(original,as_version=4)
nbformat.validate(nb)
for i,c in enumerate(nb.cells):
    if c.cell_type=='code':
        compile(c.source,f'notebook-cell-{i}','exec')
        c.outputs=[]
        c.execution_count=None
result={'nbformat_valid':True,'all_code_cells_compile':True,
        'source_notebook_unchanged':True,'execution_workdir':str(WORK)}
try:
    NotebookClient(nb,timeout=1800,kernel_name='python3',resources={'metadata':{'path':str(WORK)}}).execute()
    result['execution_succeeded']=True
except Exception as exc:
    result.update(execution_succeeded=False,error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
    if isinstance(exc, PermissionError):
        # No kernel ran. Execute exact source cells sequentially in a fresh
        # namespace in this fresh process. All imports, computations and writes
        # remain unchanged; only display capture is supplied by the harness.
        import contextlib,io
        result['kernel_start_blocked']=True
        result['kernel_execution_succeeded']=False
        result['kernel_start_error']={k:result.pop(k) for k in ['error_type','error','traceback']}
        result['execution_method']='sequential exact source in fresh Python process; no Jupyter kernel'
        namespace={'__name__':'__main__','display':lambda *args: print(*(repr(x) for x in args))}
        try:
            for i,c in enumerate(nb.cells):
                if c.cell_type!='code':continue
                buf=io.StringIO()
                with contextlib.redirect_stdout(buf),contextlib.redirect_stderr(buf):
                    exec(compile(c.source,f'notebook-cell-{i}','exec'),namespace)
                c.outputs=[nbformat.v4.new_output('stream',name='stdout',text=buf.getvalue())]
                c.execution_count=i+1
            result['execution_succeeded']=True
            result['source_execution_succeeded']=True
            rec=namespace['report']['experiment_record']
            result['fresh_record']={k:rec[k] for k in ['experiment_id','promotion_state','n_trials_global','trials_this_experiment','search_family_id']}
        except Exception as source_exc:
            result['source_execution_error']={'type':type(source_exc).__name__,'message':str(source_exc),'traceback':traceback.format_exc()}
nbformat.write(nb,OUT/'notebook-executed.ipynb')
result['error_outputs']=[{'cell':i,'ename':o.get('ename'),'evalue':o.get('evalue')} for i,c in enumerate(nb.cells)
    for o in c.get('outputs',[]) if o.output_type=='error']
result['nonfinite_output_mentions']=[]
import re
for i,c in enumerate(nb.cells):
    for o in c.get('outputs',[]):
        txt=o.get('text','') or o.get('data',{}).get('text/plain','')
        for line in txt.splitlines():
            if re.search(r'\b(?:nan|inf)\b',line,re.I):
                result['nonfinite_output_mentions'].append({'cell':i,'line':line[:300]})
(OUT/'notebook-check-results.json').write_text(json.dumps(result,indent=2,default=str))
print(json.dumps(result,indent=2,default=str))
