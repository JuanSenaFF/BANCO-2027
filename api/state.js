const {wrap,auth,db,fail}=require('../lib/server');
const {valid}=require('../state-model');
module.exports=wrap(['GET','PUT'],async(req,res)=>{const {user,token}=await auth(req);if(req.method==='GET'){const data=await db('user_state?user_id=eq.'+encodeURIComponent(user.id)+'&select=payload',{token});return res.json({state:data[0]?.payload||null});}const state=req.body?.state;if(!valid(state)||Buffer.byteLength(JSON.stringify(state))>2e6)fail(400,'Dados inválidos ou acima do limite de 2 MB.');await db('rpc/save_career_state',{token,method:'POST',body:{p_state:state}});res.json({saved:true});});
module.exports.valid=valid;
