const displayTime = minute => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
const sessionMinutes = [
  ...Array.from({length: 121}, (_, i) => 9 * 60 + 30 + i),
  ...Array.from({length: 120}, (_, i) => 13 * 60 + 1 + i),
]

// The horizontal axis contains trading minutes only; missing observations remain null.
export function tradingChartData(points) {
  const hasOpeningMinute=points.some(point=>{
    const date=new Date(new Date(point.at).getTime()+8*60*60*1000)
    return !Number.isNaN(date.getTime()) && date.getUTCHours()===13 && date.getUTCMinutes()===0 && point.price!==null && point.price!=='' && Number.isFinite(Number(point.price)) && Number(point.price)>0
  })
  const minutes=hasOpeningMinute?[...sessionMinutes.slice(0,121),13*60,...sessionMinutes.slice(121)]:sessionMinutes
  const times=minutes.map(displayTime)
  const indexes=new Map(times.map((time,index)=>[time,index]))
  const prices=times.map(()=>null)
  for (const point of points) {
    const date=new Date(new Date(point.at).getTime()+8*60*60*1000)
    if (Number.isNaN(date.getTime()) || point.price==null || point.price==='') continue
    const index=indexes.get(displayTime(date.getUTCHours()*60+date.getUTCMinutes()))
    const price=Number(point.price)
    if (index!==undefined && Number.isFinite(price) && price>0) prices[index]=price
  }
  return {times,prices}
}

export function marketChartData(points, days=1) {
  if(days===1)return tradingChartData(points)
  const grouped=new Map()
  for(const point of points){
    const at=Date.parse(point.at)
    if(!Number.isFinite(at))continue
    const day=new Date(at+8*3600000).toISOString().slice(0,10)
    if(!grouped.has(day))grouped.set(day,[])
    grouped.get(day).push(point)
  }
  const times=[],prices=[]
  for(const day of [...grouped.keys()].sort()){
    const series=tradingChartData(grouped.get(day))
    if(times.length){
      times.push(day+' 分隔')
      prices.push(null)
    }
    times.push(...series.times.map(time=>day.slice(5)+' '+time))
    prices.push(...series.prices)
  }
  return {times,prices}
}

export function chartExtremes(points, days=1) {
  const values=marketChartData(points,days).prices.filter(value=>value!==null)
  return values.length?{high:Math.max(...values),low:Math.min(...values)}:{high:null,low:null}
}

// Mark the first visible occurrence, using the same data that is drawn on the curve.
export function extremeMarkers({times,prices}) {
  const values=prices.filter(value=>value!==null)
  if(!values.length)return []
  const low=Math.min(...values),high=Math.max(...values)
  function marker(value,title,position) {
    const index=prices.indexOf(value)
    const align=index<30?'left':index>=prices.length-30?'right':'center'
    return {coord:[times[index],value],value,label:{position,align,formatter:`${title} ${value.toFixed(3)}`}}
  }
  if(low===high)return [marker(low,'最高/最低','top')]
  return [marker(low,'最低','bottom'),marker(high,'最高','top')]
}
