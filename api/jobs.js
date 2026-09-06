const {wrap,db}=require('../lib/server');
module.exports=wrap(['GET'],async(req,res)=>{const rows=await db('jobs?select=payload&order=key&limit=1000');const m=await db('collection_meta?id=eq.current&select=payload');res.json({jobs:rows.map(x=>x.payload),meta:m[0]?.payload||{}});});
