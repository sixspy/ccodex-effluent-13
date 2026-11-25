export const permitsViewTemplate = `
  <div class="panel" style="border-style:solid">
    <h3>帽值禁封拍板（当日锁死）</h3>
    <p class="muted" style="margin:0.2rem 0">{{ capPolicy.policy }}</p>
    <p style="margin:0.2rem 0">锁定状态：<span class="pass">{{ capPolicy.locked ? "已锁死" : "—" }}</span> · {{ capPolicy.as_of }}</p>
  </div>
  <div class="grid-2">
    <div class="panel">
      <h3>排放许可册（许可帽）</h3>
      <table>
        <thead><tr><th>许可号</th><th>厂</th><th>配额</th><th>COD帽</th><th>氨氮帽</th><th>总磷帽</th><th>期别</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="p in permits" :key="p.id">
            <td>{{ p.permit_code }}</td><td>{{ p.plant_code }}</td><td>{{ p.quota_m3d }}</td>
            <td class="warn">{{ p.cod_cap }}</td><td>{{ p.nh3n_cap }}</td><td>{{ p.tp_cap }}</td>
            <td>{{ p.period_label }}</td>
            <td :class="statusClass(p.status)">{{ p.status }}</td>
          </tr>
        </tbody>
      </table>
      <p class="muted" style="font-size:0.82rem">封批页快照读数高于上述帽值即红灯拒封，口径与对账页、采样页、准排页同态。</p>
    </div>
    <div class="panel">
      <h3>登记许可</h3>
      <div class="form-row"><div><label>许可号</label><input v-model="permitForm.permit_code"/></div>
      <div><label>厂 ID</label><input type="number" v-model.number="permitForm.plant_id"/></div></div>
      <div class="form-row"><div><label>配额</label><input type="number" v-model.number="permitForm.quota_m3d"/></div>
      <div><label>期别</label><input v-model="permitForm.period_label"/></div></div>
      <div class="form-row">
        <div><label>COD帽</label><input type="number" v-model.number="permitForm.cod_cap"/></div>
        <div><label>氨氮帽</label><input type="number" v-model.number="permitForm.nh3n_cap"/></div>
      </div>
      <label>总磷帽</label><input type="number" v-model.number="permitForm.tp_cap"/>
      <div class="actions"><button @click="createPermit">登记（随附帽值禁封口径）</button></div>
    </div>
  </div>`;
