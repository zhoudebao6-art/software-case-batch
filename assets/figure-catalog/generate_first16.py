from pathlib import Path
import os,csv,json,math,hashlib,zipfile,html
os.environ.setdefault('MPLCONFIGDIR','E:/codex+/cache/matplotlib')
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Circle
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'高清单图';DATA=ROOT/'数据与依据'
OUT.mkdir(exist_ok=True);DATA.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':12,'axes.labelsize':13,'xtick.labelsize':11,'ytick.labelsize':11,'axes.edgecolor':'#9aa9b3','axes.labelcolor':'#304656','xtick.color':'#465c69','ytick.color':'#465c69','grid.color':'#e1e8ec','grid.linewidth':.7,'figure.facecolor':'white','savefig.facecolor':'white','lines.linewidth':2})
C=['#236b8e','#dc8c43','#4d9b8c','#8e6aa8','#718697']
PALETTES=[
 ('靛蓝与琥珀',['#354f92','#c78316','#607d8b','#9372a0','#555f6a'],'YlGnBu'),
 ('紫罗兰与青绿',['#76518f','#287e80','#c98b52','#596f9f','#6b6871'],'PuBuGn'),
 ('赭石与石墨',['#af5f32','#46525e','#859e60','#9f7890','#6b7075'],'YlOrBr'),
 ('深绿与金色',['#28725c','#b68a27','#537da0','#a66c7e','#65736a'],'YlGn'),
 ('酒红与蓝灰',['#9b405a','#4f7f96','#be8b56','#81749d','#70636a'],'PuRd'),
 ('海军蓝与珊瑚',['#284b68','#c06a51','#4b948b','#aa9444','#6b7480'],'Blues'),
 ('梅紫与橄榄',['#855576','#7b8539','#3b8392','#be8659','#69616e'],'cividis'),
 ('黑灰与铜色',['#343b43','#a96c3c','#6e8790','#8d7b98','#686d72'],'Greys')]
CM='viridis'

records=[]
def data(n,cols,rows):
    p=DATA/(n+'.csv')
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(cols);w.writerows(rows)
    return str(p.relative_to(ROOT)).replace('\\','/')
def style(ax,grid='y'):
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis=grid,alpha=.8);ax.set_axisbelow(True)
def make(i,name,purpose,method,provenance='computed',projection=None):
    global C,CM
    palette_name,C,CM=PALETTES[(i-1)%len(PALETTES)]
    fig=plt.figure(figsize=(8.2,5.2),layout='constrained')
    ax=fig.add_subplot(111,projection=projection)
    if projection is None:style(ax)
    return fig,ax,{'id':i,'name':name,'purpose':purpose,'method':method,'provenance':provenance,'palette_name':palette_name,'colors':C.copy(),'colormap':CM,'data':[]}
def save(fig,r):
    p=OUT/f"{r['id']:02d}_{r['name']}.png";fig.savefig(p,dpi=300);plt.close(fig)
    r['image']=str(p.relative_to(ROOT)).replace('\\','/');r['sha256']=hashlib.sha256(p.read_bytes()).hexdigest();records.append(r)

# Every numerical example is computed or seeded synthetic data, never instrument measurement.
fig,ax,r=make(1,'动态响应曲线','读出变化速度、稳定值与阈值到达时刻','y=1-exp(-t/τ)，τ分别为2.0与4.0；阈值0.9')
t=np.linspace(0,12,241)
for tau,col in [(2,C[0]),(4,C[1])]:ax.plot(t,1-np.exp(-t/tau),color=col,label=f'时间常数 τ = {tau:.1f} s')
ax.axhline(.9,color=C[4],ls=':',lw=1.5,label='响应阈值 0.90')
ax.set(xlabel='时间 / s',ylabel='归一化响应',xlim=(0,12),ylim=(0,1.06));ax.legend(frameon=False,loc='lower right')
r['data']=[data('01_响应',['time_s','tau2_response','tau4_response'],zip(t,1-np.exp(-t/2),1-np.exp(-t/4)))];save(fig,r)

fig,ax,r=make(2,'阶梯与事件标记','表达设定值切换及离散控制动作','预定义分段常值：0–3s为20，3–7s为45，7–10s为30，10–12s为50')
ts=[0,3,7,10,12];v=[20,45,30,50,50]
ax.step(ts,v,where='post',color=C[0],lw=2.6);ax.scatter(ts[:-1],v[:-1],color=C[0],s=42,zorder=3)
for x,txt in [(3,'负载切换'),(7,'约束介入'),(10,'恢复设定')]:ax.axvline(x,color='#b9c5cc',ls=':',lw=1);ax.text(x+.12,56,txt,fontsize=10,rotation=0)
ax.set(xlabel='时间 / s',ylabel='控制设定 / %',xlim=(-.3,12.8),ylim=(10,64))
r['data']=[data('02_阶梯',['time_s','setpoint_percent'],zip(ts,v))];save(fig,r)

fig,ax,r=make(3,'散点与拟合残差','表达两个连续量的关系及偏离程度','固定seed=7生成y=0.72x+8+正态扰动，最小二乘拟合；非实测', 'illustrative')
rng=np.random.default_rng(7);x=np.linspace(10,90,36);y=.72*x+8+rng.normal(0,5,len(x));coef=np.polyfit(x,y,1);yp=np.polyval(coef,x)
ax.vlines(x,np.minimum(y,yp),np.maximum(y,yp),color='#bdcbd3',lw=1)
ax.scatter(x,y,c=C[0],s=40,alpha=.85,label='演示样本');ax.plot(x,yp,c=C[1],label='最小二乘拟合')
ax.set(xlabel='输入负荷 / %',ylabel='响应量 / 归一化单位');ax.legend(frameon=False)
r['data']=[data('03_拟合',['load_percent','response','fit','residual'],zip(x,y,yp,y-yp))];save(fig,r)

fig,ax,r=make(4,'小提琴与箱线分布','比较集中位置、离散性与分布形态','seed=8；三组各160次合成试算：N(42,4)、N(35,6)、N(30,3)；小提琴为核密度', 'illustrative')
rng=np.random.default_rng(8);groups=[rng.normal(m,s,160) for m,s in [(42,4),(35,6),(30,3)]]
vp=ax.violinplot(groups,showextrema=False,widths=.7)
for body,col in zip(vp['bodies'],C):body.set_facecolor(col);body.set_edgecolor(col);body.set_alpha(.25)
ax.boxplot(groups,widths=.17,showfliers=False,patch_artist=True,boxprops={'facecolor':'white','edgecolor':'#415c6b'},medianprops={'color':'#243f50','linewidth':2})
ax.set(xticks=[1,2,3],xticklabels=['方案 A','方案 B','方案 C'],ylabel='完成耗时 / ms',ylim=(10,60))
r['data']=[data('04_分布',['scheme','trial','duration_ms'],((chr(65+k),j+1,z) for k,g in enumerate(groups) for j,z in enumerate(g)))];save(fig,r)

fig,ax,r=make(5,'配对哑铃图','直接比较同一对象调整前后的差异','五个工况的演示前后值，连线只表示同一工况配对', 'illustrative')
a=np.array([42,58,48,70,63]);b=np.array([31,42,36,51,44]);yy=np.arange(5)
ax.hlines(yy,b,a,color='#c2cfd6',lw=4);ax.scatter(a,yy,color=C[1],s=72,label='调整前',zorder=3);ax.scatter(b,yy,color=C[0],s=72,label='调整后',zorder=3)
ax.set(yticks=yy,yticklabels=[f'工况 {i}' for i in range(1,6)],xlabel='单位任务能耗 / Wh',xlim=(20,80));ax.legend(frameon=False,loc='lower right');ax.grid(axis='x');ax.grid(axis='y',visible=False)
r['data']=[data('05_配对',['condition','before_Wh','after_Wh'],zip(range(1,6),a,b))];save(fig,r)

fig,ax,r=make(6,'点估计与区间图','区分平均表现和估计不确定性','seed=9，各方案40个正态合成试算值；均值及均值±1.96×样本标准差/√40，仅正态近似区间', 'illustrative')
rng=np.random.default_rng(9);gg=[rng.normal(m,s,40) for m,s in [(12,5),(8,3),(16,6),(5,2)]];mu=np.array([g.mean() for g in gg]);err=np.array([1.96*g.std(ddof=1)/np.sqrt(len(g)) for g in gg]);yy=np.arange(4)
ax.errorbar(mu,yy,xerr=err,fmt='o',color=C[0],capsize=5,ms=7,elinewidth=2)
ax.set(yticks=yy,yticklabels=['策略 A','策略 B','策略 C','策略 D'],xlabel='平均误差 / μm',xlim=(0,21));ax.grid(axis='x');ax.grid(axis='y',visible=False)
ax.text(.98,.06,'点：均值　线：均值的近似 95% 区间',transform=ax.transAxes,ha='right',fontsize=10,color='#516674')
r['data']=[data('06_区间原始',['strategy','trial','error_um'],((chr(65+k),j+1,z) for k,g in enumerate(gg) for j,z in enumerate(g)))];save(fig,r)

fig,ax,r=make(7,'经验累积分布','回答多少比例的样本落在给定阈值以内','seed=10，两个对数正态合成时延样本各240个；ECDF=i/n', 'illustrative')
rng=np.random.default_rng(10);ga=np.sort(rng.lognormal(3.4,.33,240));gb=np.sort(rng.lognormal(3.1,.25,240));pp=np.arange(1,241)/240
for g,c,l in [(ga,C[1],'基准方案'),(gb,C[0],'调整方案')]:ax.step(g,pp,where='post',color=c,label=l)
ax.axvline(40,color=C[4],ls=':',label='时延界限 40 ms');ax.set(xlabel='时延 / ms',ylabel='累计样本比例',xlim=(0,80),ylim=(0,1.03));ax.legend(frameon=False,loc='lower right')
r['data']=[data('07_累计',['rank','baseline_ms','adjusted_ms','cumulative_fraction'],zip(range(1,241),ga,gb,pp))];save(fig,r)

fig,ax,r=make(8,'增减贡献瀑布图','表达净结果如何由各增减项构成','初始100；输入+24、回收+12、损耗-18、输出-30；末值88；守恒演示', 'computed')
values=[100,24,12,-18,-30,88];labels=['初始','输入','回收','损耗','输出','期末'];curr=100
for i,v in enumerate(values):
    if i in (0,5):bottom=0;height=v;color=C[0]
    else:bottom=min(curr,curr+v);height=abs(v);color=C[2] if v>0 else C[1]
    ax.bar(i,height,bottom=bottom,color=color,width=.6)
    top=bottom+height;ax.text(i,top+3, str(v) if i in (0,5) else f'{v:+}',ha='center',fontsize=11)
    if i==0:curr=100
    elif i<5:curr+=v
    if i<5:ax.plot([i+.3,i+.7],[curr,curr],color='#a9b6c0',lw=1,ls=':')
ax.set(xticks=range(6),xticklabels=labels,ylabel='库存量 / kg',ylim=(0,160))
r['data']=[data('08_贡献',['term','amount_kg'],zip(labels,values))];save(fig,r)

fig,ax,r=make(9,'事件区间与资源占用','比较任务起止、重叠及资源使用','演示排程记录；水平条长度仅由明确起止时刻计算', 'illustrative')
tasks=[('清洗',0,3,0),('喷涂 A',3,7,1),('喷涂 B',7,11,1),('固化 A',7,13,2),('固化 B',13,19,2),('检测 A',13,15,3),('检测 B',19,21,3)]
for name,start,end,lane in tasks:
    ax.broken_barh([(start,end-start)],(lane-.23,.46),facecolors=C[lane],alpha=.85);ax.text((start+end)/2,lane,name,ha='center',va='center',color='white',fontsize=10)
ax.set(yticks=range(4),yticklabels=['清洗工位','喷涂工位','固化工位','检测工位'],xlabel='相对起始时刻 / min',xlim=(-.5,22),ylim=(-.6,3.6));ax.grid(axis='x');ax.grid(axis='y',visible=False)
r['data']=[data('09_排程',['task','start_min','end_min','resource'],tasks)];save(fig,r)

fig,ax,r=make(10,'稀疏成员点阵','只突出实际存在的成员关系，替代大面积0/1色块','四个融合组对应六个原始事件；点=实际关联，空位=未关联；无连续强度', 'schematic')
links=[(0,0),(1,0),(1,1),(2,1),(2,2),(3,2),(3,3),(5,3)]
for y in range(4):ax.hlines(y,-.2,5.2,color='#e3e9ec',lw=1)
for x,y in links:ax.scatter(x,y,s=130,color=C[0],zorder=3)
ax.set(xticks=range(6),xticklabels=[f'E{i+1}' for i in range(6)],yticks=range(4),yticklabels=['融合组 A','融合组 B','融合组 C','融合组 D'],xlabel='原始事件标识',xlim=(-.5,5.5),ylim=(3.5,-.5));ax.grid(False)
r['data']=[data('10_成员',['event','group'],((f'E{x+1}',chr(65+y)) for x,y in links))];save(fig,r)

fig,ax,r=make(11,'二部来源关系图','跟踪原始来源如何关联到融合结果','来源节点到结果节点的显式成员关系；位置与边宽不表示数值', 'schematic')
left=[(.12,y) for y in [.88,.65,.42,.19]];right=[(.85,y) for y in [.8,.5,.2]];edges=[(0,0),(1,0),(1,1),(2,1),(2,2),(3,2)]
for a,b in edges:ax.plot([left[a][0],right[b][0]],[left[a][1],right[b][1]],color='#b0c3cf',lw=1.8,zorder=1)
for pts,prefix,col in [(left,'来源',C[0]),(right,'结果',C[2])]:
    for i,(x,y) in enumerate(pts):ax.scatter(x,y,s=850,color=col,zorder=2);ax.text(x,y,str(i+1),ha='center',va='center',color='white');ax.text(x+(-.07 if x<.5 else .07),y,f'{prefix} {i+1}',ha='right' if x<.5 else 'left',va='center',fontsize=12)
ax.set(xlim=(-.05,1.05),ylim=(.03,1));ax.axis('off')
r['data']=[data('11_来源关系',['source','result'],((a+1,b+1) for a,b in edges))];save(fig,r)

fig,ax,r=make(12,'状态迁移环图','表达状态间允许的转移与失败回路','演示状态机；箭头表示允许转移，不表示概率、数量或时间', 'schematic')
pos={'就绪':(-.8,0),'执行':(0,.68),'完成':(.8,0),'待修正':(0,-.68)}
ed=[('就绪','执行','启动'),('执行','完成','成功'),('执行','待修正','校验失败'),('待修正','就绪','修正完成')]
for a,b,label in ed:
    pa,pb=np.array(pos[a]),np.array(pos[b]);d=pb-pa;u=d/np.linalg.norm(d);start=pa+.18*u;end=pb-.18*u
    rad=.12 if (a,b)!=('执行','待修正') else .08
    ax.add_patch(FancyArrowPatch(start,end,connectionstyle=f'arc3,rad={rad}',arrowstyle='-|>',mutation_scale=17,color='#8ba6b5',lw=2))
for j,(name,(x,y)) in enumerate(pos.items()):ax.add_patch(Circle((x,y),.18,facecolor=C[j],edgecolor='white',lw=2));ax.text(x,y,name,ha='center',va='center',color='white',fontsize=12)
for x,y,txt in [(-.58,.48,'启动'),(.58,.48,'成功'),(.25,-.03,'校验失败'),(-.62,-.48,'修正完成')]:ax.text(x,y,txt,ha='center',fontsize=11,color='#485d6b')
ax.set(xlim=(-1.15,1.15),ylim=(-1,1),aspect='equal');ax.axis('off')
r['data']=[data('12_迁移',['from','to','condition'],ed)];save(fig,r)

fig,ax,r=make(13,'等值线与可行域','同时识别连续响应场和约束边界','响应f=(x-1)^2+0.6(y+0.4)^2；可行域x+y≤1.8且x≥-1')
x=np.linspace(-2,3,101);y=np.linspace(-2,2,81);xx,yy=np.meshgrid(x,y);z=(xx-1)**2+.6*(yy+.4)**2
cs=ax.contour(xx,yy,z,levels=[.5,1,2,4,6,9,12],colors=C[0],linewidths=1);ax.clabel(cs,inline=True,fontsize=9,fmt='%g')
mask=np.where((xx+yy<=1.8)&(xx>=-1),1,np.nan);ax.contourf(xx,yy,mask,levels=[.5,1.5],colors=[C[2]],alpha=.13)
ax.plot(x,1.8-x,c=C[1],ls='--',label='约束边界 x + y = 1.8');ax.axvline(-1,c=C[1],ls=':');ax.scatter([1],[-.4],c=C[3],s=45,label='响应极小点')
ax.set(xlabel='归一化参数 x',ylabel='归一化参数 y',xlim=(-2,3),ylim=(-2,2));ax.legend(frameon=False,fontsize=10,loc='upper right')
r['data']=[data('13_场',['x','y','response','feasible'],zip(xx.ravel(),yy.ravel(),z.ravel(),((xx+yy<=1.8)&(xx>=-1)).ravel()))];save(fig,r)

fig,ax,r=make(14,'三维观测几何','表达真实空间位置、轨迹与观测射线','半径100mm圆弧；角度-60至60度，观测点z=20mm，目标(0,0,100)mm',projection='3d')
theta=np.deg2rad(np.linspace(-60,60,41));x=100*np.sin(theta);y=100*(1-np.cos(theta));z=np.full(41,20.0)
ax.plot(x,y,z,c=C[0]);idx=[0,10,20,30,40];ax.scatter(x[idx],y[idx],z[idx],s=32,c=C[0],marker='s',label='观测位置');ax.scatter([0],[0],[100],s=50,c=C[1],label='目标点')
for j in idx:ax.plot([x[j],0],[y[j],0],[z[j],100],c='#adc5d4',lw=1)
ax.set(xlabel='x / mm',ylabel='y / mm',zlabel='z / mm');ax.set_box_aspect((2,1,1.1));ax.view_init(elev=23,azim=-55);ax.legend(frameon=False,fontsize=10,loc='upper left')
r['data']=[data('14_几何',['theta_deg','x_mm','y_mm','z_mm'],zip(np.rad2deg(theta),x,y,z))];save(fig,r)

fig,ax,r=make(15,'流线与矢量场','表达方向、局部速度及运动路径','二维解析旋转场u=-y、v=x；速度sqrt(x²+y²)，非流体求解或实测')
x=np.linspace(-2,2,25);y=np.linspace(-2,2,25);xx,yy=np.meshgrid(x,y);u=-yy;v=xx;speed=np.hypot(u,v)
st=ax.streamplot(x,y,u,v,color=speed,cmap=CM,density=.9,linewidth=1.4,arrowsize=1.2)
fig.colorbar(st.lines,ax=ax,pad=.03,label='速度模 / 归一化单位');ax.set(xlabel='归一化位置 x',ylabel='归一化位置 y',aspect='equal');ax.grid(False)
r['data']=[data('15_向量场',['x','y','u','v','speed'],zip(xx.ravel(),yy.ravel(),u.ravel(),v.ravel(),speed.ravel()))];save(fig,r)

fig,ax,r=make(16,'联合概率矩阵','保留真正需要两维交叉读取的矩阵','四项联合概率分别0.59、0.05、0.33、0.03，总和1；不等于条件概率','illustrative')
z=np.array([[.59,.05],[.33,.03]]);im=ax.imshow(z,vmin=0,vmax=1,cmap=CM,aspect='auto')
for (i,j),v in np.ndenumerate(z):ax.text(j,i,f'{v:.2f}',ha='center',va='center',fontsize=18,color='white' if v>.5 else '#284d4a')
ax.set(xticks=[0,1],xticklabels=['设备 B 正常','设备 B 异常'],yticks=[0,1],yticklabels=['设备 A 正常','设备 A 异常'],xlabel='设备 B 状态',ylabel='设备 A 状态');ax.grid(False);ax.spines[:].set_visible(False);fig.colorbar(im,ax=ax,label='联合概率',pad=.04)
r['data']=[data('16_联合概率',['state_A','state_B','joint_probability'],((i,j,z[i,j]) for i in range(2) for j in range(2)))];save(fig,r)

# Contact sheets are presentation aids; original 300dpi plots stay separately available.
font='C:/Windows/Fonts/msyh.ttc'
ft=lambda n:ImageFont.truetype(font,n)
group_names=['趋势与分布','差异与贡献','时间与关系','空间与二维结构']
for k in range(4):
    sheet=Image.new('RGB',(2000,1540),'#f2f5f7');d=ImageDraw.Draw(sheet)
    d.text((55,24),f'图型表达样张  {k+1}/4 · {group_names[k]}',font=ft(34),fill='#203e50')
    d.text((56,74),'演示 / 可复算样张 · 非案件实测结果 · 图型按问题选择，不是固定套餐',font=ft(20),fill='#617784')
    for j,r in enumerate(records[k*4:(k+1)*4]):
        x=40+(j%2)*990;y=125+(j//2)*700
        d.rounded_rectangle((x,y,x+950,y+675),radius=16,fill='white')
        d.text((x+24,y+18),f"{r['id']:02d}  {r['name']}",font=ft(27),fill='#26485d')
        im=Image.open(ROOT/r['image']).convert('RGB');im.thumbnail((914,565),Image.Resampling.LANCZOS)
        sheet.paste(im,(x+(950-im.width)//2,y+70))
        d.text((x+24,y+635),r['purpose'],font=ft(18),fill='#5d727f')
    sheet.save(ROOT/f'总览{k+1}_{group_names[k]}.png')
manifest={'purpose':'用户选图型与表达形式的样张，不是案件交付，不是现场实测','items':records,'note':'每个图的计算式或固定随机种子见生成样张.py与本清单；关系图仅表示显式演示结构。'}
(ROOT/'样张依据.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
with (ROOT/'图型目录.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['编号','图型','适用问题','数据性质','计算或构造依据','高清文件']);w.writerows((r['id'],r['name'],r['purpose'],r['provenance'],r['method'],r['image']) for r in records)
cards=''.join(f'<article><h2>{r["id"]:02d} {html.escape(r["name"])}</h2><a href="{r["image"]}"><img src="{r["image"]}"></a><p>{html.escape(r["purpose"])}</p><small>{html.escape(r["method"])}</small></article>' for r in records)
(ROOT/'打开图型总览.html').write_text('<!doctype html><meta charset="utf-8"><title>图型表达样张</title><style>body{font:16px "Microsoft YaHei";margin:32px;background:#eef3f5;color:#264353}main{display:grid;grid-template-columns:repeat(2,minmax(320px,1fr));gap:24px}article{background:white;border-radius:14px;padding:22px}img{width:100%}h2{font-size:20px}small{color:#617582}@media(max-width:800px){main{grid-template-columns:1fr}}</style><h1>16种图型与表达样张</h1><p>演示或可复算数据，不冒充案件实测。点击图片可查看高清原图；不同图型用于不同问题，不按数量强制选用。</p><main>'+cards+'</main>',encoding='utf-8')
print(json.dumps({'figures':len(records),'output':str(ROOT),'images':len(list(OUT.glob('*.png')))},ensure_ascii=False))
