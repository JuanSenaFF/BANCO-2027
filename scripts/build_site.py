"""Copy only public assets; generate public configuration from deployment variables."""
import os,json,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'dist';out.mkdir(exist_ok=True)
for name in ['index.html','styles.css','app.js','engine.js','skills.js','config.js','data.js','data-auto.js','jobs.json','market-history.json',*(f'data-{i}.js' for i in range(1,7))]:
    shutil.copy2(root/name,out/name)
if os.getenv('SUPABASE_URL'):
    config={'apiBase':os.getenv('PUBLIC_API_BASE',''),'supabaseUrl':os.environ['SUPABASE_URL'],'supabaseAnonKey':os.getenv('SUPABASE_ANON_KEY','')}
    (out/'config.js').write_text('window.BANCO_CONFIG = '+json.dumps(config)+';\n')
(out/'.nojekyll').touch()
