export const sealViewTemplate = `
  <div class="panel" style="border-style:solid">
    <h3>帽值禁封口径（当日锁死）</h3>
    <p class="muted" style="margin:0.2rem 0">{{ capPolicy.policy }}</p>
  </div>
  <div class="grid-2">
    <div class="panel">
      <h3>封批快照（正式区）</h3>
      <table>
        <thead><tr><th>封批号</th><th>采样</th><th>代</th><th>快照</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="s in seals" :key="s.id">
            <td>{{ s.seal_ref }}</td><td>{{ s.sample_code }}</td><td>{{ s.sample_generation }}</td>
            <td>{{ s.snapshot }}</td><td>{{ s.sealed_at }}</td>
          </tr>
        </tbody>
      </table>
      <h3 style="margin-top:1rem">影子快照草稿（shadow 区，非正式）</h3>
      <table>
        <thead><tr><th>采样</th><th>代</th><th>快照</th><th>帽值</th><th>草稿状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="d in sealDrafts" :key="d.id">
            <td>{{ d.sample_code }}</td><td>{{ d.sample_generation }}</td><td>{{ d.snapshot }}</td>
            <td :class="d.cap_passed ? 'pass' : 'fail'">{{ d.cap_passed ? "帽内" : "帽值不符" }}</td>
            <td>{{ d.status }}</td>
            <td>
              <button v-if="d.cap_passed && d.status!=='复核通过已升正'" class="secondary"
                      @click="promoteDraft(d.id)">复核升正</button>
              <span v-else class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h3>执行封批</h3>
      <label>可封批采样（含帽值闸门结论）</label>
      <select v-model.number="sealForm.sample_id">
        <option v-for="s in sealableSamples" :key="s.id" :value="s.id">
          {{ s.sample_code }} · {{ s.status }} · {{ capText(s) }}
        </option>
      </select>
      <div v-if="sealableSamples.find(s=>s.id===sealForm.sample_id)" class="kv" style="margin:0.4rem 0">
        <span>许可帽 COD/氨氮/总磷</span>
        <span>{{ fmtCaps(sealableSamples.find(s=>s.id===sealForm.sample_id)) }}</span>
        <span>读数</span><span>{{ fmtMetrics(sealableSamples.find(s=>s.id===sealForm.sample_id).metrics) }}</span>
      </div>
      <label>快照（可空自动）</label><input v-model="sealForm.snapshot"/>
      <div class="actions"><button class="warn" @click="createSeal">封批升代（帽值不符即红灯回退）</button></div>
    </div>
  </div>`;
