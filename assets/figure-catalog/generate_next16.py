from pathlib import Path
exec((Path(__file__).resolve().parent/'generate_first16.py').read_text(encoding='utf-8').split('# Every numerical')[0])
prior=json.loads((ROOT/'样张依据.json').read_text(encoding='utf-8'))['items']
prior=[r for r in prior if r['id']<=16]

fig,ax,r=make(17,'单边幅值频谱','识别信号的主频与谐波','fs=500Hz，2秒，s=sin(2π30t)+0.35sin(2π85t)；整周期无窗FFT，单边幅值2|FFT|/N')
t=np.arange(1000)/500;s=np.sin(2*np.pi*30*t)+.35*np.sin(2*np.pi*85*t);f=np.fft.rfftfreq(len(t),1/500);a=2*abs(np.fft.rfft(s))/len(s);a[[0,-1]]/=2
ax.plot(f,a,color=C[0]);ax.scatter([30,85],[1,.35],c=C[1],zorder=3);ax.annotate('30 Hz', (30,1),xytext=(42,.95),arrowprops={'arrowstyle':'-','color':C[4]});ax.annotate('85 Hz',(85,.35),xytext=(98,.5),arrowprops={'arrowstyle':'-','color':C[4]});ax.set(xlim=(0,150),ylim=(0,1.15),xlabel='频率 / Hz',ylabel='单边幅值 / V')
r['data']=[data('17_信号',['time_s','signal_V'],zip(t,s)),data('17_频谱',['frequency_Hz','amplitude_V'],zip(f,a))];save(fig,r)

fig,ax,r=make(18,'时频谱','定位频率随时间的变化过程','fs=400Hz，6秒；sin[2π(20t+5t²)]线性扫频；Hann窗256点、重叠224点；功率谱密度')
t=np.arange(2400)/400;s=np.sin(2*np.pi*(20*t+5*t*t));power,freq,bins,im=ax.specgram(s,NFFT=256,Fs=400,noverlap=224,cmap=CM,vmin=-70,vmax=-5)
ax.set(xlabel='时间 / s',ylabel='频率 / Hz',ylim=(0,120));ax.grid(False);fig.colorbar(im,ax=ax,label='功率谱密度 / dB(V²/Hz)',pad=.03)
r['data']=[data('18_扫频',['time_s','signal_V','instant_frequency_Hz'],zip(t,s,20+10*t)),data('18_时频',['time_s','frequency_Hz','PSD_V2_per_Hz'],((tt,ff,power[i,j]) for j,tt in enumerate(bins) for i,ff in enumerate(freq)))];save(fig,r)

fig,ax,r=make(19,'三维响应曲面','直观显示两参数共同影响响应的形态','z=exp[-(x²+0.7y²)]+0.15x，二维解析响应，不冒充实验',projection='3d')
x=np.linspace(-2,2,61);y=np.linspace(-2,2,61);xx,yy=np.meshgrid(x,y);z=np.exp(-(xx**2+.7*yy**2))+.15*xx
surf=ax.plot_surface(xx,yy,z,cmap=CM,linewidth=0,antialiased=True,alpha=.95);ax.set(xlabel='参数 x',ylabel='参数 y',zlabel='归一化响应');ax.view_init(25,-55);fig.colorbar(surf,ax=ax,shrink=.62,pad=.12,label='响应值')
r['data']=[data('19_曲面',['x','y','response'],zip(xx.ravel(),yy.ravel(),z.ravel()))];save(fig,r)

fig,ax,r=make(20,'极坐标方向响应','比较不同角度下的方向敏感性','r=0.3+0.7cos²θ；θ是物理方向，r为归一化响应',projection='polar')
theta=np.linspace(0,2*np.pi,361);rad=.3+.7*np.cos(theta)**2
ax.plot(theta,rad,c=C[0]);ax.fill(theta,rad,color=C[0],alpha=.12);ax.set_ylim(0,1.1);ax.set_yticks([.25,.5,.75,1]);ax.set_rlabel_position(45);ax.grid(alpha=.6)
r['data']=[data('20_方向',['angle_deg','response'],zip(np.rad2deg(theta),rad))];save(fig,r)

fig,ax,r=make(21,'时序着色轨迹','读取空间路径、时间方向与偏移','x=10cos(t)，y=6sin(t)+0.15t，t∈[0,2π]；解析演示轨迹')
t=np.linspace(0,2*np.pi,181);x=10*np.cos(t);y=6*np.sin(t)+.15*t
ax.plot(x,y,c='#c5d2d9',lw=1);sc=ax.scatter(x,y,c=t,cmap=CM,s=17);ax.scatter([x[0]],[y[0]],marker='o',s=90,facecolors='none',edgecolors=C[1],lw=2);ax.scatter([x[-1]],[y[-1]],marker='x',s=80,c=C[1]);ax.set(xlabel='x / m',ylabel='y / m',aspect='equal');fig.colorbar(sc,ax=ax,label='时间 / s',pad=.03)
ax.text(.02,.96,'空心圈：起点  ×：终点',transform=ax.transAxes,va='top',fontsize=10)
r['data']=[data('21_轨迹',['time_s','x_m','y_m'],zip(t,x,y))];save(fig,r)

fig,ax,r=make(22,'帕累托前沿','比较多个目标之间无法同时改善的权衡','seed=22；成本随机20–100，误差=100/成本+U(0,3)；两目标均最小化，逐点支配判断','illustrative')
rng=np.random.default_rng(22);cost=rng.uniform(20,100,55);error=100/cost+rng.uniform(0,3,55)
front=np.array([not np.any((cost<=cost[i])&(error<=error[i])&((cost<cost[i])|(error<error[i]))) for i in range(len(cost))]);order=np.argsort(cost[front])
ax.scatter(cost[~front],error[~front],c='#b7c6ce',s=36,label='其他候选');ax.plot(cost[front][order],error[front][order],'o-',c=C[0],label='非支配候选');ax.set(xlabel='相对成本',ylabel='平均误差 / %');ax.legend(frameon=False)
r['data']=[data('22_多目标',['cost','error_percent','pareto'],zip(cost,error,front))];save(fig,r)

fig,ax,r=make(23,'三元组分图','显示总和为1的三种组分及其组合效应','seed=23，Dirichlet(2,2,2)生成90组配比；响应=0.5A+0.8B+0.2C，重心坐标绘制','illustrative')
rng=np.random.default_rng(23);abc=rng.dirichlet([2,2,2],90);h=np.sqrt(3)/2;xx=abc[:,1]+.5*abc[:,2];yy=h*abc[:,2];resp=abc@np.array([.5,.8,.2])
ax.plot([0,1,.5,0],[0,0,h,0],c=C[4])
for q in [.2,.4,.6,.8]:
    ax.plot([q, .5+.5*q],[0,h*(1-q)],c='#e1e8ec',lw=.7);ax.plot([1-q,.5*(1-q)],[0,h*(1-q)],c='#e1e8ec',lw=.7);ax.plot([.5*q,1-.5*q],[h*q,h*q],c='#e1e8ec',lw=.7)
sc=ax.scatter(xx,yy,c=resp,cmap=CM,s=28);ax.text(-.04,-.04,'A = 100%',ha='center');ax.text(1.04,-.04,'B = 100%',ha='center');ax.text(.5,h+.04,'C = 100%',ha='center');ax.set(xlim=(-.13,1.13),ylim=(-.1,h+.12),aspect='equal');ax.axis('off');fig.colorbar(sc,ax=ax,shrink=.75,label='组合响应')
r['data']=[data('23_组分',['A','B','C','response'],zip(*abc.T,resp))];save(fig,r)

fig,ax,r=make(24,'平行坐标','比较多个方案的指标组合与短板','四方案、五项同向效益评分0–100；每轴固定共同范围，非原始异量纲值','illustrative')
scores=np.array([[85,62,72,80,58],[70,87,66,65,83],[78,76,89,71,74],[62,68,75,92,90]])
for j,row in enumerate(scores):ax.plot(range(5),row,'o-',c=C[j],label=f'方案 {chr(65+j)}',alpha=.9)
for x in range(5):ax.axvline(x,c='#d8e2e7',lw=1,zorder=0)
ax.set(xticks=range(5),xticklabels=['效率评分','稳定评分','精度评分','低耗评分','维护评分'],ylabel='同向评分 / 分',ylim=(0,105));ax.legend(frameon=False,ncol=4,loc='lower center',fontsize=10)
r['data']=[data('24_评分',['scheme','efficiency','stability','accuracy','economy','maintenance'],((chr(65+i),*row) for i,row in enumerate(scores)))];save(fig,r)

fig,ax,r=make(25,'山脊分布','对比连续工况下分布位置与形态迁移','五个解析正态密度N(20+7k,(3+0.5k)²)，k=0..4；同一密度放大系数8，不是样本估计')
x=np.linspace(5,65,401)
rows=[]
for k in range(5):
    m=20+7*k;sd=3+.5*k;den=np.exp(-.5*((x-m)/sd)**2)/(sd*np.sqrt(2*np.pi));ax.fill_between(x,k,k+8*den,color=C[k],alpha=.45);ax.plot(x,k+8*den,color=C[k],lw=1.6);rows.extend(zip([k+1]*len(x),x,den))
ax.set(yticks=range(5),yticklabels=[f'工况 {k+1}' for k in range(5)],xlabel='响应量',ylim=(-.15,5.1));ax.grid(False)
r['data']=[data('25_密度',['condition','response','density'],rows)];save(fig,r)

fig,ax,r=make(26,'六边形密度分箱','大量散点重叠时显示聚集结构','seed=26，3500组联合正态样本，均值(50,50)、协方差[[150,95],[95,120]]；颜色为分箱计数','illustrative')
rng=np.random.default_rng(26);pts=rng.multivariate_normal([50,50],[[150,95],[95,120]],3500);hb=ax.hexbin(*pts.T,gridsize=30,mincnt=1,cmap=CM);ax.set(xlabel='特征 A',ylabel='特征 B');fig.colorbar(hb,ax=ax,label='样本数',pad=.03);ax.grid(False)
r['data']=[data('26_样本',['feature_A','feature_B'],pts)];save(fig,r)

fig,ax,r=make(27,'敏感性龙卷风图','识别参数扰动对结果影响的大小与方向','线性模型R=100+Σcᵢδᵢ，c=[70,-45,30,18,-8]；逐参数δ=±0.1，其余为0')
c=np.array([70,-45,30,18,-8]);minus=-.1*c;plus=.1*c
for i in range(5):ax.plot([minus[i],plus[i]],[i,i],c='#b9c8d2',lw=7);ax.scatter(minus[i],i,c=C[0],s=58,zorder=3,label='参数 -10%' if i==0 else None);ax.scatter(plus[i],i,c=C[1],s=58,zorder=3,label='参数 +10%' if i==0 else None)
ax.axvline(0,c=C[4],lw=1);ax.set(yticks=range(5),yticklabels=['参数 A','参数 B','参数 C','参数 D','参数 E'],xlabel='相对基准结果的变化量',ylim=(4.6,-.6),xlim=(-9,9));ax.grid(axis='x');ax.grid(axis='y',visible=False);ax.legend(frameon=False,loc='lower right',fontsize=10)
r['data']=[data('27_敏感性',['parameter','coefficient','minus10_change','plus10_change'],zip(list('ABCDE'),c,minus,plus))];save(fig,r)

fig,ax,r=make(28,'堆叠面积构成','同时呈现总量变化和各来源构成','t=0..24；A=40+10sin(2πt/24)，B=25+5cos(2πt/24)，C=15+0.5t；仅独立可加来源')
t=np.linspace(0,24,97);a=40+10*np.sin(2*np.pi*t/24);b=25+5*np.cos(2*np.pi*t/24);c=15+.5*t
ax.stackplot(t,a,b,c,colors=C[:3],labels=['来源 A','来源 B','来源 C'],alpha=.85);ax.set(xlabel='时间 / h',ylabel='来源量 / m³',xlim=(0,24),ylim=(0,120));ax.legend(frameon=False,ncol=3,loc='upper left')
r['data']=[data('28_构成',['time_h','A_m3','B_m3','C_m3','total_m3'],zip(t,a,b,c,a+b+c))];save(fig,r)

fig,ax,r=make(29,'衰减振荡相图','观察状态收敛、振荡与方向','x=e^(-0.15t)cos(2t)，v=dx/dt；t=0..25，解析轨迹')
t=np.linspace(0,25,1001);x=np.exp(-.15*t)*np.cos(2*t);v=np.exp(-.15*t)*(-.15*np.cos(2*t)-2*np.sin(2*t))
ax.plot(x,v,c=C[0],lw=1.7)
for j in [35,135,235]:ax.annotate('',xy=(x[j+8],v[j+8]),xytext=(x[j],v[j]),arrowprops={'arrowstyle':'->','color':C[1],'lw':2})
ax.scatter([x[0],0],[v[0],0],c=[C[1],C[3]],s=40,zorder=3);ax.axhline(0,c='#d2dee4',lw=1);ax.axvline(0,c='#d2dee4',lw=1);ax.set(xlabel='归一化位移 x',ylabel='归一化速度 v');ax.grid(False)
r['data']=[data('29_相图',['time_s','x','v'],zip(t,x,v))];save(fig,r)

fig,ax,r=make(30,'可靠度曲线','比较运行时间增加时的模型存活概率','Weibull模型R=exp[-(t/η)^β]；β=2，η=1000和1400h；理论模型，无实测故障证据')
t=np.linspace(0,2500,251)
for eta,col in [(1000,C[1]),(1400,C[0])]:ax.plot(t,np.exp(-(t/eta)**2),c=col,label=f'尺度参数 η = {eta} h')
ax.axhline(.5,c=C[4],ls=':',lw=1);ax.set(xlabel='运行时间 / h',ylabel='可靠度 R(t)',xlim=(0,2500),ylim=(0,1.03));ax.legend(frameon=False)
r['data']=[data('30_可靠度',['time_h','eta1000','eta1400'],zip(t,np.exp(-(t/1000)**2),np.exp(-(t/1400)**2)))];save(fig,r)

fig,ax,r=make(31,'气泡多变量比较','在两个指标上同时编码第三个规模量','八方案演示值；横轴能耗、纵轴产量；气泡面积与批量成正比','illustrative')
x=np.array([25,35,42,50,58,65,72,82]);y=np.array([34,55,46,70,67,90,80,96]);volume=np.array([20,40,70,35,90,65,120,80])
ax.scatter(x,y,s=volume*6,c=C[0],alpha=.45,edgecolors=C[0])
for i,(xx,yy) in enumerate(zip(x,y)):ax.annotate(chr(65+i),(xx,yy),xytext=(0,12),textcoords='offset points',ha='center',fontsize=10)
for q in [20,60,120]:ax.scatter([],[],s=q*6,c=C[0],alpha=.45,label=f'批量 {q}')
ax.set(xlabel='能耗 / kWh',ylabel='产量 / 件',xlim=(15,95),ylim=(15,112));ax.legend(frameon=False,loc='center right',fontsize=9,labelspacing=1.7)
r['data']=[data('31_气泡',['scheme','energy_kWh','output_count','batch_size'],zip(list('ABCDEFGH'),x,y,volume))];save(fig,r)

fig,ax,r=make(32,'滞回环与方向','揭示加载和卸载路径不同','输入x=sin(t)，输出y=sin(t-0.45)，t=0..2π；相位滞后参数化演示，不是材料实测')
t=np.linspace(0,2*np.pi,361);x=np.sin(t);y=np.sin(t-.45);ax.plot(x,y,c=C[0],lw=2.5)
for j in [25,130,240]:ax.annotate('',xy=(x[j+8],y[j+8]),xytext=(x[j],y[j]),arrowprops={'arrowstyle':'->','color':C[1],'lw':2})
ax.axhline(0,c='#cbd9e1',lw=1);ax.axvline(0,c='#cbd9e1',lw=1);ax.set(xlabel='归一化输入',ylabel='归一化输出',xlim=(-1.2,1.2),ylim=(-1.2,1.2),aspect='equal');ax.grid(False)
r['data']=[data('32_滞回',['phase_rad','input','output'],zip(t,x,y))];save(fig,r)

records=prior+records
font='C:/Windows/Fonts/msyh.ttc';ft=lambda n:ImageFont.truetype(font,n)
names=['信号与方向','轨迹与方案','分布与构成','状态与性能']
for k in range(4):
    sheet=Image.new('RGB',(2000,1540),'#f2f5f7');d=ImageDraw.Draw(sheet)
    d.text((55,24),f'新增图型样张 {k+5}/8 · {names[k]}',font=ft(34),fill='#203e50')
    d.text((56,74),'演示 / 可复算样张 · 非案件实测结果 · 根据技术问题选择，不是固定套餐',font=ft(20),fill='#617784')
    for j,r in enumerate(records[16+k*4:20+k*4]):
        x=40+(j%2)*990;y=125+(j//2)*700;d.rounded_rectangle((x,y,x+950,y+675),radius=16,fill='white');d.text((x+24,y+18),f"{r['id']:02d}  {r['name']}",font=ft(27),fill='#26485d')
        im=Image.open(ROOT/r['image']).convert('RGB');im.thumbnail((914,565),Image.Resampling.LANCZOS);sheet.paste(im,(x+(950-im.width)//2,y+70));d.text((x+24,y+635),r['purpose'],font=ft(18),fill='#5d727f')
    sheet.save(ROOT/f'总览{k+5}_{names[k]}.png')
(ROOT/'样张依据.json').write_text(json.dumps({'purpose':'32种可选表达样张，不是案件实测或固定图型套餐','selection':'按原材料、要证明的问题与真实数据结构选图；同批避免机械套版，必要矩阵保留；解释按最终图的实际编码衔接实施例','items':records},ensure_ascii=False,indent=2),encoding='utf-8')
with (ROOT/'图型目录.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['编号','图型','适用问题','数据性质','计算或构造依据','高清文件']);w.writerows((r['id'],r['name'],r['purpose'],r['provenance'],r['method'],r['image']) for r in records)
cards=''.join(f'<article><h2>{r["id"]:02d} {html.escape(r["name"])}</h2><a href="{r["image"]}"><img loading="lazy" src="{r["image"]}"></a><p>{html.escape(r["purpose"])}</p><small>{html.escape(r["method"])}</small></article>' for r in records)
(ROOT/'打开图型总览.html').write_text('<!doctype html><meta charset="utf-8"><title>32种图型表达样张 · 多色版</title><style>body{font:16px "Microsoft YaHei";margin:32px;background:#eef3f5;color:#264353}main{display:grid;grid-template-columns:repeat(2,minmax(320px,1fr));gap:24px}article{background:white;border-radius:14px;padding:22px}img{width:100%}h2{font-size:20px}small{color:#617582}@media(max-width:800px){main{grid-template-columns:1fr}}</style><h1>32种图型与表达样张 · 8组配色</h1><p><a href="配色总览.png">查看8组配色</a> · 本页交替展示仅供选色，实际案件内同一对象保持同色。</p><p>点击单图可看300dpi原图。样张采用演示或可复算数据，不是案件实测结果。按技术问题与数据结构自主设计选图，不照搬配图组合；矩阵确实适用时保留。</p><main>'+cards+'</main>',encoding='utf-8')
assert len(records)==32 and len({r['id'] for r in records})==32
for r in records:
    assert hashlib.sha256((ROOT/r['image']).read_bytes()).hexdigest()==r['sha256']
    for q in r['data']:assert (ROOT/q).is_file()
print(json.dumps({'figures':len(records),'new':16,'data_files':len(list(DATA.glob('*.csv')))},ensure_ascii=False))
