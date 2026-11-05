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

export function chartExtremes(points) {
  const values=tradingChartData(points).prices.filter(value=>value!==null)
  return values.length?{high:Math.max(...values),low:Math.min(...values)}:{high:null,low:null}
}
