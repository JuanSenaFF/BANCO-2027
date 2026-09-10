const {wrap,auth,db,fail}=require('../lib/server');
const E=require('../engine');
const skills=require('../skills');
module.exports=wrap(['GET'],async(req,res)=>{const {user,token}=await auth(req);const state=await db('user_state?user_id=eq.'+encodeURIComponent(user.id)+'&select=payload',{token});const s=state[0]?.payload;if(!s)fail(400,'Preencha e salve seu perfil.');const rows=await db('jobs?select=payload&limit=1000'),jobs=rows.map(({payload})=>E.normalize(payload));res.json({matches:jobs.map(j=>{const analysis=E.evaluate(j,s.profile,skills,s.prefs,s.answers);return {key:j.key,...analysis,action:E.actionDecision(j,analysis)};}),studyPriorities:E.priorities(jobs,s.profile,skills,s.prefs,s.answers)});});
