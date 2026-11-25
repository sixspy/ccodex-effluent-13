export const releaseViewTemplate = `
  <div class="panel" style="border-style:solid">
    <h3>准排帽值闸门（与封批页同态）</h3>
    <p class="muted" style="margin:0.2rem 0">读数高于许可帽的快照在准排页即拒收，不得进入准排与封批链。</p>
  </div>
  <div class="grid-2">
    <div class="panel">
      <h3>准排放记录</h3>
      <table>
        <thead><tr><th>准排号</th><th>采样</th><th>口</th><th>值班</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="r in releases" :key="r.id">
            <td>{{ r.release_ref }}</td><td>{{ r.sample_code }}</td><td>{{ r.outfall_code }}</td>
            <td>{{ r.officer }}</td><td>{{ r.released_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>签发准排</h3>
      <label>已裁定采样（帽值状态随行）</label>
      <select v-model.number="releaseForm.sample_id">
        <option v-for="s in releasableSamples" :key="s.id" :value="s.id">
          {{ s.sample_code }} · {{ s.status }} · {{ capText(s) }}
        </option>
      </select>
      <div v-if="releasableSamples.find(s=>s.id===releaseForm.sample_id)" class="kv" style="margin:0.4rem 0">
        <span>许可帽 COD/氨氮/总磷</span>
        <span>{{ fmtCaps(releasableSamples.find(s=>s.id===releaseForm.sample_id)) }}</span>
        <span>读数</span><span>{{ fmtMetrics(releasableSamples.find(s=>s.id===releaseForm.sample_id).metrics) }}</span>
      </div>
      <label>值班员</label><input v-model="releaseForm.officer"/>
      <div class="actions"><button @click="createRelease">准排（帽值不符即红灯拒收）</button></div>
    </div>
  </div>`;
