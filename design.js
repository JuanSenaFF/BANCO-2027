/* Visual behavior inspired by Spell UI's Special Text and Label Input patterns.
   Ported to the project's dependency-free DOM architecture. */
(()=>{
'use strict';
const reduce=matchMedia('(prefers-reduced-motion: reduce)');
const symbols='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<>/{}$%';
let previousRoute='';

function directControl(label){
  return [...label.children].find(child=>/^(INPUT|SELECT|TEXTAREA)$/.test(child.tagName));
}

function labelText(label,control){
  return [...label.childNodes]
    .filter(node=>node!==control&&node.nodeType===Node.TEXT_NODE)
    .map(node=>node.textContent.trim()).filter(Boolean).join(' ');
}

function enhanceLabels(root=document){
  root.querySelectorAll('label:not(.check):not(.label-input)').forEach(label=>{
    const control=directControl(label);
    if(!control||control.type==='file'||control.type==='checkbox'||control.type==='radio')return;
    const text=labelText(label,control);
    if(!text)return;
    [...label.childNodes].filter(node=>node!==control&&node.nodeType===Node.TEXT_NODE).forEach(node=>node.remove());
    const caption=document.createElement('span');
    caption.className='label-input__caption';
    caption.textContent=text;
    label.classList.add('label-input');
    label.insertBefore(caption,control);
    if(control.tagName!=='SELECT'&&!control.placeholder)control.placeholder=' ';
    if(control.type==='password')addPasswordToggle(label,control);
  });
}

function addPasswordToggle(label,input){
  if(label.querySelector('.password-toggle'))return;
  const toggle=document.createElement('button');
  toggle.type='button';
  toggle.className='password-toggle';
  toggle.setAttribute('aria-label','Mostrar senha');
  toggle.setAttribute('aria-pressed','false');
  toggle.textContent='MOSTRAR';
  toggle.addEventListener('click',()=>{
    const reveal=input.type==='password';
    input.type=reveal?'text':'password';
    toggle.textContent=reveal?'OCULTAR':'MOSTRAR';
    toggle.setAttribute('aria-label',reveal?'Ocultar senha':'Mostrar senha');
    toggle.setAttribute('aria-pressed',String(reveal));
    input.focus({preventScroll:true});
  });
  label.append(toggle);
}

function specialText(element){
  if(!element||element.dataset.specialText==='done')return;
  element.dataset.specialText='done';
  const finalText=element.textContent;
  element.setAttribute('aria-label',finalText);
  if(reduce.matches||!finalText.trim())return;
  let frame=0;
  const total=Math.min(18,Math.max(10,Math.ceil(finalText.length*.7)));
  const timer=setInterval(()=>{
    const resolved=Math.floor(frame/total*finalText.length);
    element.textContent=[...finalText].map((char,index)=>{
      if(char===' '||index<resolved)return char;
      return symbols[(frame*7+index*11)%symbols.length];
    }).join('');
    frame++;
    if(frame>total){clearInterval(timer);element.textContent=finalText;}
  },20);
}

function routeTransition(){
  const main=document.querySelector('#main');
  if(!main)return;
  const route=location.hash.split('/')[0]||'#dashboard';
  if(route!==previousRoute&&!reduce.matches){
    main.getAnimations().forEach(animation=>animation.cancel());
    main.animate(
      [{opacity:.45,transform:'translate3d(12px,0,0)'},{opacity:1,transform:'translate3d(0,0,0)'}],
      {duration:220,easing:'cubic-bezier(0.23, 1, 0.32, 1)'}
    );
  }
  previousRoute=route;
  specialText(main.querySelector('.pagehead h1'));
  enhanceLabels(main);
}

const main=document.querySelector('#main');
const modalBody=document.querySelector('#modalBody');
if(main)new MutationObserver(records=>{
  enhanceLabels(main);
  if(records.some(record=>record.target===main))routeTransition();
}).observe(main,{childList:true,subtree:true});
if(modalBody)new MutationObserver(()=>enhanceLabels(modalBody)).observe(modalBody,{childList:true,subtree:true});
enhanceLabels(document);
routeTransition();
})();
