document.fonts.ready.then(()=>{const sc=parseFloat(getComputedStyle(document.body).getPropertyValue('--title-scale'))||1;
document.querySelectorAll('.fit').forEach(el=>{
  const s0=Math.round(+el.dataset.max*(el.dataset.noscale?1:sc)),mn=+el.dataset.min;const cs=getComputedStyle(el);
  const avail=el.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
  const sp=document.createElement('span');sp.style.whiteSpace='nowrap';while(el.firstChild)sp.appendChild(el.firstChild);el.appendChild(sp);
  let s=s0;el.style.fontSize=s+'px';
  while(sp.getBoundingClientRect().width>avail&&s>mn){s-=2;el.style.fontSize=s+'px'}
  if(sp.getBoundingClientRect().width>avail){sp.style.whiteSpace='normal';el.style.whiteSpace='normal';el.dataset.overflow='wrap'}
});
/* menu boards: shrink the menu block until everything fits on the page */
const main=document.querySelector('main'),ms=document.querySelector('.menus');
if(ms){const H=main.getBoundingClientRect().bottom;
const over=()=>{const ft=document.querySelector('footer');let lb=0;ms.querySelectorAll('.item,.row').forEach(e=>{lb=Math.max(lb,e.getBoundingClientRect().bottom)});
const limit=ft?ft.getBoundingClientRect().top:H-60;return (ft&&ft.getBoundingClientRect().bottom>H-30)||lb>limit+1};
let z=1;while(over()&&z>0.62){z-=0.03;ms.style.zoom=z}if(over())ms.dataset.overflow='menus';
/* few menus: grow each item until the free space is used (max 1.45x) */
else if(z===1){const kids=[...ms.children];const wide=()=>kids.some(e=>e.scrollWidth>e.clientWidth+1||e.getBoundingClientRect().right>ms.getBoundingClientRect().right+1);
let g=1;const set=v=>kids.forEach(e=>e.style.zoom=v);
while(g<1.45){g=+(g+0.05).toFixed(2);set(g);if(over()||wide()){g=+(g-0.05).toFixed(2);set(g);break}}
if(g>1)ms.dataset.grow=g}}
/* ad cards: keep the body text clear of the price badge */
const bd=document.querySelector('main>.body'),pw=document.querySelector('.pricewrap');
if(bd&&pw){const a=bd.getBoundingClientRect(),b=pw.getBoundingClientRect(),W=main.getBoundingClientRect().right;
if(a.right>b.left&&a.left<b.right&&a.bottom>b.top&&a.top<b.bottom&&b.left>a.left+300){bd.style.right=(W-b.left+28)+'px';bd.dataset.shifted=1}}
document.body.dataset.ready=1})
