window.BANCO2027={"jobs":[],"domains":{"B3":"b3.com.br","Cielo":"cielo.com.br","Getnet":"getnet.com.br","Pismo":"pismo.io","PicPay":"picpay.com","Banco BV":"bancobv.com.br","Banco BMG":"bancobmg.com.br","Banco Daycoval":"daycoval.com.br","Dock":"dock.tech","Núclea":"nuclea.com.br","Sicoob":"sicoob.com.br","Sicredi":"sicredi.com.br","FitBank":"fitbank.com.br","Banco Inter":"inter.co","Bradesco":"bradesco.com.br","Stone":"stone.com.br","Mercado Livre / Mercado Pago":"mercadopago.com.br","BTG Pactual":"btgpactual.com","XP Inc.":"xpinc.com","C6 Bank":"c6bank.com.br","PagBank":"pagbank.com.br","Itaú Unibanco":"itau.com.br","Santander Brasil":"santander.com.br","BMP":"bmpmoneyplus.com.br","Nava | Tech for Business":"nava.com.br","ANBIMA":"anbima.com.br","Grupo Bancorbrás":"bancorbras.com.br","Via Certa Promotora":"acertapromotora.com.br"},"icons":{"Python":["python","3776AB"],"SQL":["postgresql","4169E1"],"Java":["openjdk","ED8B00"],".NET/C#":["dotnet","512BD4"],"JavaScript/Node":["nodedotjs","339933"],"REST/APIs":["postman","FF6C37"],"Git":["git","F05032"],"Testes":["pytest","0A9EDC"],"AWS":["amazonwebservices","FF9900"],"Azure":["microsoftazure","0078D4"],"GCP":["googlecloud","4285F4"],"Docker":["docker","2496ED"],"Kubernetes":["kubernetes","326CE5"],"CI/CD":["githubactions","2088FF"],"Microsserviços":["kubernetes","7B61FF"],"Mensageria":["apachekafka","111111"],"Observabilidade":["grafana","F46800"],"Cloud":["icloud","3693F3"],"Linux":["linux","FCC624"],"Terraform/IaC":["terraform","844FBA"],"Dados/BI":["databricks","FF3621"],"Automação":["n8n","EA4B71"],"IA/ML":["openai","111111"],"Segurança":["owasp","111111"],"Crédito/Risco":["stripe","635BFF"],"POO/Design":["diagramsdotnet","F08705"],"Troubleshooting/Produção":["sentry","362D59"]}};
document.write('<script src="data-auto.js?v='+Date.now()+'"></scr'+'ipt>');
window.addEventListener('DOMContentLoaded',function(){
  var tabs=document.querySelector('.tabs');
  if(!tabs||document.getElementById('updateJobsBtn')) return;
  var b=document.createElement('button');
  b.id='updateJobsBtn';
  b.className='tabbtn';
  b.type='button';
  b.textContent='↻ Atualizar vagas';
  b.title='Buscar novas vagas agora';
  b.addEventListener('click',function(){
    var url='https://github.com/JuanSenaFF/BANCO-2027/actions/workflows/update-vagas.yml';
    window.open(url,'_blank','noopener');
  });
  tabs.appendChild(b);
});
