var fs0 = require('fs');
var PAGE_CANDIDATES = ['宿迁职业技术学院作息时间表.html', 'index.html'];
var PAGE = PAGE_CANDIDATES.filter(function(f){ return fs0.existsSync(f); })[0] || 'index.html';
// 验证 index.html 新增的"多套作息模板 + 特殊日解析"逻辑
// 提取页面内数据区代码（不依赖 DOM），在沙箱中 eval，逐项断言
const fs = require('fs');
const html = fs.readFileSync(PAGE, 'utf8');

// 提取数据区：从 START 定义到 stateText（含 resolveSchedule / buildSegments / stateAt / countdown）
const startIdx = html.indexOf('var START = 7*60+30');
const endIdx = html.indexOf('function stateText(');
let code = html.slice(startIdx, endIdx);

// 沙箱执行
const vm = require('node:vm');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(code, sandbox, { filename: 'index-data.js' });

let pass = 0, fail = 0;
function assert(name, cond, extra) {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (extra ? '  → ' + extra : '')); }
}

// ---- 1. resolveSchedule 星期规则 ----
const R = sandbox.resolveSchedule, SCH = sandbox.SCHEDULES;
assert('周四 → weekday', R(new Date('2026-09-24T10:00:00')) === SCH.weekday);
assert('周六 → saturday', R(new Date('2026-09-26T10:00:00')) === SCH.saturday);
assert('周日 → sunday', R(new Date('2026-09-27T10:00:00')) === SCH.sunday);
assert('周一 → weekday', R(new Date('2026-09-28T10:00:00')) === SCH.weekday);

// ---- 2. SPECIAL 特殊日覆盖优先 ----
const before = JSON.stringify(sandbox.SPECIAL);
sandbox.SPECIAL['2026-10-01'] = 'holiday';
sandbox.SPECIAL['2026-10-03'] = 'weekday'; // 周六调休补课
if (R(new Date('2026-10-01T10:00:00')) !== SCH.holiday){
  console.log('  [debug] SPECIAL keys =', JSON.stringify(sandbox.SPECIAL),
              '| 生成的 key =', '2026-10-01');
}
assert('特殊日(周四) → holiday 覆盖', R(new Date('2026-10-01T10:00:00')) === SCH.holiday);
assert('特殊日(周六补课) → weekday 覆盖', R(new Date('2026-10-03T10:00:00')) === SCH.weekday);
assert('未覆盖的周六(10-10?) → 走星期规则', R(new Date('2026-10-10T10:00:00')) === SCH.saturday);
sandbox.SPECIAL = JSON.parse(before);

// ---- 3. 模板数据正确性 ----
const WT = SCH.weekday.tracks, ST = SCH.saturday.tracks, SU = SCH.sunday.tracks, HT = SCH.holiday.tracks;
assert('4 套模板各 4 个学院', [WT, ST, SU, HT].every(t => t.length === 4));
assert('周六 4 学院统一 8:00 上课', ST.every(t => t.times[0] === '8:00-8:45'));
assert('周六 4 学院 close=19:00', ST.every(t => t.close === '19:00'));
assert('周六 4 学院 rest=[5..12]', ST.every(t => JSON.stringify(t.rest) === JSON.stringify([5,6,7,8,9,10,11,12])));
assert('周六通识教育与其他学院同表', ST[2].times.join() === ST[0].times.join());
assert('周日 close 沿用周内', SU[0].close === WT[0].close && SU[3].close === WT[3].close);
assert('周日白天 rest=[0..8]', SU.every(t => JSON.stringify(t.rest) === JSON.stringify([0,1,2,3,4,5,6,7,8])));
assert('周日晚自习沿用周内(晚一晚二晚三)', SU[0].times[10] === WT[0].times[10] && SU[2].times[12] === WT[2].times[12]);
assert('周日白天段 = 7:30-晚休开始', SU[0].times[0] === '7:30-' + WT[0].times[9].split('-')[0]);
assert('holiday close=19:00 全休息', HT.every(t => t.close === '19:00' && t.rest.length === 13));
assert('weekday 无 rest 标记', WT.every(t => !t.rest));

// ---- 4. buildSegments / stateAt 状态机 ----
const buildSegments = sandbox.buildSegments, stateAt = sandbox.stateAt;
function stAt(i, hhmm){
  return stateAt(i, (parseInt(hhmm.split(':')[0])*60 + parseInt(hhmm.split(':')[1])));
}
// 手动模拟 applySchedule：TRACKS/SEGS 赋值为指定模板
function useTemplate(tpl){
  sandbox.TRACKS = tpl;
  sandbox.SEGS = tpl.map(buildSegments);
}
useTemplate(ST);
assert('周六上午 9:00 → 第二节课(am)', stAt(2, '09:00').cat === 'am');
assert('周六下午 15:00 → 休息(free)', stAt(2, '15:00').cat === 'free');
assert('周六 18:30 → 休息(free)', stAt(0, '18:30').cat === 'free');
assert('周六 19:30 → 已关寝(closed)', stAt(0, '19:30').cat === 'closed');
useTemplate(SU);
assert('周日上午 10:00 → 休息(free)', stAt(1, '10:00').cat === 'free');
assert('周日 18:00 → 休息(free)', stAt(0, '18:00').cat === 'free');
assert('周日 18:40 → 晚一(night)', stAt(0, '18:40').cat === 'night');
assert('周日 21:20 → 就寝准备(prep)', stAt(2, '21:20').cat === 'prep');
useTemplate(HT);
assert('放假中午 12:00 → 休息(free)', stAt(3, '12:00').cat === 'free');
assert('放假 20:00 → 已关寝(closed)', stAt(3, '20:00').cat === 'closed');

// ---- 5. countdown 休息段不提示 ----
const countdown = sandbox.countdown;
useTemplate(ST);
const cdSat = countdown(0, 15*60, 15*3600); // 周六 15:00
assert('周六休息段无倒计时', cdSat === null);
useTemplate(SU);
const cdSun = countdown(0, 18*60+40, (18*60+40)*60); // 周日 18:40 晚一
assert('周日晚上课中倒计时存在', cdSun !== null && cdSun.kind === 'end');

console.log('\n结果: ' + pass + ' 通过, ' + fail + ' 失败');
process.exit(fail ? 1 : 0);
//（注：内容由AI生成）
