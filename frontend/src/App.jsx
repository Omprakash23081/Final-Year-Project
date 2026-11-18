import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import {
  Activity, BarChart3, Bus, Database, Download, FileText, Gauge,
  LayoutDashboard, MapPin, Settings, TrainFront, Upload, WandSparkles
} from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line,
  LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis
} from "recharts";
import { api } from "./api";

const nav = [
  ["/", "Overview", LayoutDashboard],
  ["/forecast", "Demand Forecasting", Activity],
  ["/optimization", "Route Optimization", Gauge],
  ["/fleet", "Fleet Management", Bus],
  ["/routes", "Route Management", MapPin],
  ["/data", "Data Management", Database],
  ["/reports", "Reports", FileText],
  ["/settings", "Settings", Settings],
];

function Shell() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><TrainFront size={22}/></div><div><strong>TransitAI</strong><span>Command Center</span></div></div>
        <nav>{nav.map(([to, label, Icon]) => (
          <NavLink key={to} to={to} end={to === "/"}><Icon size={18}/><span>{label}</span></NavLink>
        ))}</nav>
        <div className="sidebar-status"><span className="status-dot"/> System operational</div>
      </aside>
      <main className="main">
        <header className="topbar"><div><p>AI Operations</p><h1>Transport Analytics</h1></div><div className="live-chip">LIVE <span/></div></header>
        <Routes>
          <Route path="/" element={<Overview/>}/>
          <Route path="/forecast" element={<Forecast/>}/>
          <Route path="/optimization" element={<Optimization/>}/>
          <Route path="/fleet" element={<Fleet/>}/>
          <Route path="/routes" element={<RoutesPage/>}/>
          <Route path="/data" element={<DataPage/>}/>
          <Route path="/reports" element={<Reports/>}/>
          <Route path="/settings" element={<SettingsPage/>}/>
        </Routes>
      </main>
    </div>
  );
}

function Page({ title, subtitle, action, children }) {
  return <section className="page"><div className="page-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>;
}

function Card({ title, value, meta, icon: Icon, tone }) {
  return <div className="stat-card"><div className={`stat-icon ${tone || ""}`}>{Icon && <Icon size={20}/>}</div><div><span>{title}</span><strong>{value}</strong>{meta && <small>{meta}</small>}</div></div>;
}

function Overview() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/api/dashboard").then(r => setData(r.data)).catch(console.error); }, []);
  if (!data) return <Page title="Loading overview..."/>;
  return <Page title="Overview" subtitle="Network performance and demand intelligence">
    <div className="stats-grid">
      <Card title="Registered Routes" value={data.total_routes} meta="Active network" icon={MapPin} tone="blue"/>
      <Card title="Transport Stops" value={data.total_stops} meta="Across all routes" icon={Activity} tone="cyan"/>
      <Card title="Available Vehicles" value={`${data.available_vehicles}/${data.total_vehicles}`} meta="Fleet availability" icon={Bus} tone="green"/>
      <Card title="Average Demand" value={data.average_demand} meta="Passengers per record" icon={Gauge} tone="amber"/>
      <Card title="Predicted Demand" value={data.predicted_demand} meta="24-hour forecast" icon={BarChart3} tone="violet"/>
      <Card title="Fleet Utilization" value={`${data.vehicle_utilization}%`} meta="Current allocation" icon={Bus} tone="blue"/>
    </div>
    <div className="chart-grid">
      <div className="panel chart-wide"><div className="panel-head"><div><h3>Passenger demand by hour</h3><p>Observed aggregate demand</p></div></div>
        <ResponsiveContainer width="100%" height={280}><AreaChart data={data.hourly_demand}><defs><linearGradient id="demand" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3b82f6" stopOpacity={0.35}/><stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/></linearGradient></defs><CartesianGrid strokeDasharray="3 3" stroke="#23324a"/><XAxis dataKey="hour" stroke="#8090a8"/><YAxis stroke="#8090a8"/><Tooltip/><Area type="monotone" dataKey="demand" stroke="#60a5fa" fill="url(#demand)"/></AreaChart></ResponsiveContainer>
      </div>
      <div className="panel"><div className="panel-head"><div><h3>Route distribution</h3><p>Passenger volume</p></div></div>
        <ResponsiveContainer width="100%" height={280}><BarChart data={data.route_distribution}><CartesianGrid strokeDasharray="3 3" stroke="#23324a"/><XAxis dataKey="route_id" stroke="#8090a8"/><YAxis stroke="#8090a8"/><Tooltip/><Bar dataKey="demand" fill="#38bdf8" radius={[5,5,0,0]}/></BarChart></ResponsiveContainer>
      </div>
    </div>
    <div className="panel"><div className="panel-head"><div><h3>High-demand routes</h3><p>Ranked by recorded passenger volume</p></div></div><table><thead><tr><th>Route</th><th>Passenger demand</th><th>Status</th></tr></thead><tbody>{data.high_demand_routes.map(r => <tr key={r.route_id}><td>{r.route_id}</td><td>{r.demand}</td><td><span className="badge amber">Monitor</span></td></tr>)}</tbody></table></div>
  </Page>;
}

function Forecast() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const train = async () => { setLoading(true); try { const r = await api.post("/api/forecast/train"); setResult(r.data); } catch (e) { alert(e.response?.data?.detail || "Training failed"); } setLoading(false); };
  useEffect(() => { api.post("/api/forecast/train").then(r => setResult(r.data)).catch(() => {}); }, []);
  return <Page title="Demand Forecasting" subtitle="Random Forest and Seasonal Naive comparison" action={<button className="primary" onClick={train} disabled={loading}><WandSparkles size={17}/>{loading ? "Training..." : "Train models"}</button>}>
    {result ? <>
      <div className="notice"><strong>{result.synthetic ? "Synthetic data" : "Uploaded data"}</strong><span>Forecast labels are predictions, not observed demand.</span></div>
      <div className="stats-grid">
        {Object.entries(result.metrics).map(([name, m]) => <Card key={name} title={name.replaceAll("_"," ").toUpperCase()} value={`${m.mae} MAE`} meta={`RMSE ${m.rmse} · WAPE ${m.wape}%`} icon={Activity} tone="blue"/>)}
      </div>
      <div className="chart-grid">
        <div className="panel chart-wide"><div className="panel-head"><h3>Actual vs predicted</h3></div><ResponsiveContainer width="100%" height={300}><LineChart data={result.comparison}><CartesianGrid strokeDasharray="3 3" stroke="#23324a"/><XAxis dataKey="timestamp" hide/><YAxis stroke="#8090a8"/><Tooltip/><Legend/><Line type="monotone" dataKey="actual" stroke="#94a3b8" dot={false}/><Line type="monotone" dataKey="predicted" stroke="#3b82f6" dot={false}/></LineChart></ResponsiveContainer></div>
        <div className="panel"><div className="panel-head"><h3>Next 24 hours</h3></div><div className="table-scroll"><table><thead><tr><th>Time</th><th>Route</th><th>Demand</th></tr></thead><tbody>{result.forecast.slice(0,24).map((f,i) => <tr key={i}><td>{new Date(f.timestamp).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})}</td><td>{f.route_id}</td><td>{f.predicted_demand}</td></tr>)}</tbody></table></div></div>
      </div>
    </> : <div className="empty">Train the forecasting models to view analysis.</div>}
  </Page>;
}

function Optimization() {
  const [data,setData]=useState(null); const [loading,setLoading]=useState(false);
  const run=async()=>{setLoading(true);try{const r=await api.post("/api/optimization/run");setData(r.data)}catch(e){alert(e.response?.data?.detail||"Optimization failed")}setLoading(false)};
  useEffect(()=>{api.get("/api/optimization").then(r=>setData(r.data)).catch(()=>{});},[]);
  return <Page title="Route Optimization" subtitle="PuLP-constrained fleet and frequency allocation" action={<button className="primary" onClick={run} disabled={loading}>{loading?"Optimizing...":"Run optimization"}</button>}>
    {!data?.plans ? <div className="empty">Run optimization to generate an allocation plan.</div> : <>
      <div className="notice"><strong>{data.feasible ? "Feasible plan" : "Capacity shortfall detected"}</strong><span>{data.total_unmet_demand} unmet demand · Fleet used: {data.fleet_used} · Engine: {data.engine}</span></div>
      <div className="panel table-scroll"><table><thead><tr><th>Route</th><th>Predicted demand</th><th>Trips</th><th>Vehicles</th><th>Utilization</th><th>Unmet demand</th><th>Cost</th><th>Status</th></tr></thead><tbody>{data.plans.map(p=><tr key={p.route_id}><td><strong>{p.route_code}</strong><small>{p.route_name}</small></td><td>{p.predicted_demand}</td><td>{p.required_trips}</td><td>{p.recommended_vehicles}</td><td>{p.vehicle_utilization}%</td><td>{p.unmet_demand}</td><td>₹{p.estimated_operating_cost}</td><td><span className={`badge ${p.feasible?"green":"amber"}`}>{p.feasible?"Feasible":"Shortfall"}</span></td></tr>)}</tbody></table></div>
    </>}
  </Page>;
}

function Fleet() {
  const [vehicles,setVehicles]=useState([]); const [routes,setRoutes]=useState([]);
  const [form,setForm]=useState({vehicle_code:"",capacity:50,available:true,route_id:""});
  const load=()=>Promise.all([api.get("/api/vehicles"),api.get("/api/routes")]).then(([v,r])=>{setVehicles(v.data);setRoutes(r.data)});
  useEffect(()=>{load()},[]);
  const submit=async(e)=>{e.preventDefault();await api.post("/api/vehicles",{...form,route_id:form.route_id?Number(form.route_id):null});setForm({vehicle_code:"",capacity:50,available:true,route_id:""});load()};
  return <Page title="Fleet Management" subtitle="Vehicle capacity and route assignments">
    <div className="layout-two"><div className="panel"><div className="panel-head"><h3>Add vehicle</h3></div><form className="form" onSubmit={submit}><label>Vehicle code<input value={form.vehicle_code} onChange={e=>setForm({...form,vehicle_code:e.target.value})} required/></label><label>Capacity<input type="number" min="1" value={form.capacity} onChange={e=>setForm({...form,capacity:Number(e.target.value)})}/></label><label>Assigned route<select value={form.route_id} onChange={e=>setForm({...form,route_id:e.target.value})}><option value="">Unassigned</option>{routes.map(r=><option key={r.id} value={r.id}>{r.route_code} - {r.name}</option>)}</select></label><label className="check"><input type="checkbox" checked={form.available} onChange={e=>setForm({...form,available:e.target.checked})}/> Available for allocation</label><button className="primary">Add vehicle</button></form></div>
    <div className="panel table-scroll"><div className="panel-head"><h3>Fleet inventory</h3></div><table><thead><tr><th>Vehicle</th><th>Capacity</th><th>Route</th><th>Status</th></tr></thead><tbody>{vehicles.map(v=><tr key={v.id}><td><strong>{v.vehicle_code}</strong></td><td>{v.capacity} seats</td><td>{v.route_id||"Unassigned"}</td><td><span className={`badge ${v.available?"green":"amber"}`}>{v.available?"Available":"Unavailable"}</span></td></tr>)}</tbody></table></div></div>
  </Page>;
}

function RoutesPage() {
  const [routes,setRoutes]=useState([]);const [stops,setStops]=useState([]);
  const [form,setForm]=useState({route_code:"",name:"",distance_km:10,estimated_travel_min:30,min_frequency:2,max_frequency:12,operating_cost:500});
  const load=()=>Promise.all([api.get("/api/routes"),api.get("/api/stops")]).then(([r,s])=>{setRoutes(r.data);setStops(s.data)});
  useEffect(()=>{load()},[]);
  const submit=async(e)=>{e.preventDefault();await api.post("/api/routes",form);setForm({route_code:"",name:"",distance_km:10,estimated_travel_min:30,min_frequency:2,max_frequency:12,operating_cost:500});load()};
  const remove=async(id)=>{await api.delete(`/api/routes/${id}`);load()};
  return <Page title="Route Management" subtitle="Network routes, stops and graph metadata">
    <div className="layout-two"><div className="panel"><div className="panel-head"><h3>Add route</h3></div><form className="form" onSubmit={submit}><label>Route code<input value={form.route_code} onChange={e=>setForm({...form,route_code:e.target.value})} required/></label><label>Route name<input value={form.name} onChange={e=>setForm({...form,name:e.target.value})} required/></label><div className="form-grid"><label>Distance (km)<input type="number" value={form.distance_km} onChange={e=>setForm({...form,distance_km:Number(e.target.value)})}/></label><label>Travel (min)<input type="number" value={form.estimated_travel_min} onChange={e=>setForm({...form,estimated_travel_min:Number(e.target.value)})}/></label></div><button className="primary">Add route</button></form></div>
    <div className="panel"><div className="panel-head"><h3>Route network</h3></div><div className="route-network">{routes.map(r=><div className="route-node" key={r.id}><span/><div><strong>{r.route_code}</strong><small>{r.name}</small></div><button className="icon-button" onClick={()=>remove(r.id)}>×</button></div>)}</div><p className="muted">{stops.length} stops associated across the network</p></div></div>
  </Page>;
}

function DataPage() {
  const [file,setFile]=useState(null);const [stats,setStats]=useState(null);const [preview,setPreview]=useState([]);
  const load=()=>{api.get("/api/data/statistics").then(r=>setStats(r.data));api.get("/api/data/passenger?limit=50").then(r=>setPreview(r.data));};
  useEffect(load,[]);
  const upload=async()=>{if(!file)return;const fd=new FormData();fd.append("file",file);try{await api.post("/api/data/passenger/upload",fd,{headers:{"Content-Type":"multipart/form-data"}});load()}catch(e){alert(e.response?.data?.detail||"Upload failed")}};
  const generate=async()=>{await api.post("/api/data/generate-synthetic");load()};
  return <Page title="Data Management" subtitle="Passenger datasets, validation and synthetic generation">
    <div className="layout-two"><div className="panel"><div className="panel-head"><h3>Upload passenger CSV</h3></div><div className="upload"><Upload size={28}/><p>Required: timestamp, route_id, stop_id, passenger_count</p><input type="file" accept=".csv" onChange={e=>setFile(e.target.files[0])}/><button className="primary" onClick={upload} disabled={!file}>Upload CSV</button></div></div><div className="panel"><div className="panel-head"><h3>Dataset summary</h3></div>{stats?<div className="stats-grid compact"><Card title="Rows" value={stats.row_count} icon={Database}/><Card title="Routes" value={stats.route_count} icon={MapPin}/><Card title="Stops" value={stats.stop_count} icon={Activity}/><Card title="Synthetic" value={stats.synthetic_rows||0} icon={WandSparkles}/></div>:<div className="empty">No data</div>}<button className="secondary" onClick={generate}><WandSparkles size={16}/>Generate synthetic dataset</button></div></div>
    <div className="panel table-scroll"><div className="panel-head"><h3>Data preview</h3></div><table><thead><tr><th>Timestamp</th><th>Route</th><th>Stop</th><th>Passengers</th><th>Source</th></tr></thead><tbody>{preview.map((r,i)=><tr key={i}><td>{r.timestamp}</td><td>{r.route_id}</td><td>{r.stop_id}</td><td>{r.passenger_count}</td><td><span className={`badge ${r.synthetic?"violet":"green"}`}>{r.synthetic?"Synthetic":"Observed"}</span></td></tr>)}</tbody></table></div>
  </Page>;
}

function Reports() {
  const download=(type,format="csv")=>{window.open(`${api.defaults.baseURL}/api/reports/${type}/${format}`,"_blank")};
  const reports=["passenger","forecast","optimization","fleet"];
  return <Page title="Reports and Analytics" subtitle="Export structured operational reports"><div className="report-grid">{reports.map(type=><div className="panel report-card" key={type}><div className="stat-icon blue"><FileText size={20}/></div><div><h3>{type[0].toUpperCase()+type.slice(1)} report</h3><p>CSV and PDF export of current backend data</p></div><div><button className="secondary" onClick={()=>download(type,"csv")}><Download size={16}/>CSV</button> <button className="secondary" onClick={()=>download(type,"pdf")}><Download size={16}/>PDF</button></div></div>)}</div></Page>;
}

function SettingsPage(){return <Page title="Settings" subtitle="Application configuration"><div className="panel"><div className="panel-head"><h3>System settings</h3></div><div className="settings-row"><div><strong>API endpoint</strong><p>Backend FastAPI service</p></div><code>{api.defaults.baseURL}</code></div><div className="settings-row"><div><strong>Data source</strong><p>Labels indicate whether records are synthetic or observed</p></div><span className="badge violet">SQLite</span></div></div></Page>}

export default function App(){return <Shell/>;}
