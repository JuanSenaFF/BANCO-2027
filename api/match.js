const {wrap,auth,db,fail}=require('../lib/server');
const E=require('../engine');
const skills=require('../skills');
module.exports=wrap(['GET'],async(req,res)=>{const {user,token}=await auth(req);const state=await db('user_state?user_id=eq.'+encodeURIComponent(user.id)+'&select=payload',{token});const s=state[0]?.payload;if(!s)fail(400,'Preencha e salve seu perfil.');const rows=await db('jobs?select=payload&limit=1000');res.json({matches:rows.map(({payload:j})=>({key:j.key,...E.evaluate(E.normalize(j),s.profile,skills,s.prefs,s.answers)}))});});
