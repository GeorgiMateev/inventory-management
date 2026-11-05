<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-row">
          <label class="budget-label" for="budget-slider">{{ t('restocking.sliderLabel') }}</label>
          <span class="budget-value">{{ money(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          class="budget-slider"
          type="range"
          min="0"
          :max="maxBudget"
          :step="sliderStep"
          v-model.number="budget"
          :style="{ '--fill': fillPercent + '%' }"
        />
        <div class="budget-scale">
          <span>{{ money(0) }}</span>
          <span>{{ money(maxBudget) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ money(budget) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.plannedSpend') }}</div>
          <div class="stat-value">{{ money(plannedSpend) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ money(remainingBudget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.leadTime') }}</div>
          <div class="stat-value">{{ t('restocking.days', { count: orderLeadTime }) }}</div>
        </div>
      </div>

      <div v-if="confirmation" class="confirmation">
        <strong>{{ t('restocking.confirmTitle') }}</strong>
        <span>
          {{ t('restocking.confirmMessage', {
            orderNumber: confirmation.order_number,
            leadTime: t('restocking.days', { count: confirmation.lead_time_days })
          }) }}
        </span>
        <router-link to="/orders" class="confirmation-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendation') }} ({{ recommendation.length }})</h3>
          <button
            type="button"
            class="place-order"
            :disabled="recommendation.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="recommendation.length === 0" class="empty-state">
          {{ t('restocking.empty') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.shortfall') }}</th>
                <th>{{ t('restocking.table.orderQty') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in recommendation" :key="row.item_sku">
                <td><strong>{{ row.item_sku }}</strong></td>
                <td>{{ translateProductName(row.item_name) }}</td>
                <td>
                  <span :class="['badge', row.trend]">{{ t(`trends.${row.trend}`) }}</span>
                </td>
                <td>{{ row.shortfall }}</td>
                <td><strong>{{ row.quantity }}</strong></td>
                <td>{{ money(row.unit_cost) }}</td>
                <td><strong>{{ money(row.lineTotal) }}</strong></td>
                <td>{{ t('restocking.days', { count: row.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    const submitting = ref(false)
    const submitError = ref(null)
    const confirmation = ref(null)

    const money = (amount) => formatCurrency(amount, currentCurrency.value)

    const getShortfall = (f) => Math.max(0, f.forecasted_demand - f.current_stock)

    // Items that need restocking, ranked: increasing trend first, then largest shortfall
    const ranked = computed(() => {
      return forecasts.value
        .map(f => ({ ...f, shortfall: getShortfall(f) }))
        .filter(f => f.shortfall > 0)
        .sort((a, b) => {
          const aInc = a.trend === 'increasing' ? 0 : 1
          const bInc = b.trend === 'increasing' ? 0 : 1
          if (aInc !== bInc) return aInc - bInc
          return b.shortfall - a.shortfall
        })
    })

    const totalShortfallCost = computed(() => {
      return ranked.value.reduce((sum, f) => sum + f.shortfall * f.unit_cost, 0)
    })

    const sliderStep = computed(() => {
      const total = totalShortfallCost.value
      if (total <= 5000) return 100
      if (total <= 50000) return 500
      if (total <= 500000) return 1000
      return 5000
    })

    const maxBudget = computed(() => {
      const step = sliderStep.value
      return Math.max(step, Math.ceil(totalShortfallCost.value / step) * step)
    })

    const fillPercent = computed(() => {
      return maxBudget.value > 0 ? Math.min(100, (budget.value / maxBudget.value) * 100) : 0
    })

    // Greedy fill within budget
    const recommendation = computed(() => {
      let remaining = budget.value
      const result = []
      for (const item of ranked.value) {
        if (!(item.unit_cost > 0)) continue
        const quantity = Math.min(item.shortfall, Math.floor(remaining / item.unit_cost))
        if (quantity <= 0) continue
        const lineTotal = quantity * item.unit_cost
        remaining -= lineTotal
        result.push({ ...item, quantity, lineTotal })
      }
      return result
    })

    const plannedSpend = computed(() => {
      return recommendation.value.reduce((sum, r) => sum + r.lineTotal, 0)
    })

    const remainingBudget = computed(() => Math.max(0, budget.value - plannedSpend.value))

    const orderLeadTime = computed(() => {
      return recommendation.value.reduce((max, r) => Math.max(max, r.lead_time_days), 0)
    })

    const loadData = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        budget.value = Math.round(maxBudget.value / 2 / sliderStep.value) * sliderStep.value
      } catch (err) {
        error.value = t('restocking.loadError') + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (recommendation.value.length === 0 || submitting.value) return
      submitting.value = true
      submitError.value = null
      confirmation.value = null
      try {
        const items = recommendation.value.map(r => ({ sku: r.item_sku, quantity: r.quantity }))
        confirmation.value = await api.createRestockingOrder(items)
      } catch (err) {
        const detail = err.response && err.response.data && err.response.data.detail
        submitError.value = typeof detail === 'string' && detail ? detail : t('restocking.orderError')
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadData)

    return {
      t,
      translateProductName,
      loading,
      error,
      budget,
      maxBudget,
      sliderStep,
      fillPercent,
      recommendation,
      plannedSpend,
      remainingBudget,
      orderLeadTime,
      submitting,
      submitError,
      confirmation,
      money,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 1rem;
}

.budget-label {
  color: #64748b;
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #2563eb;
}

.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 8px;
  border-radius: 4px;
  outline: none;
  cursor: pointer;
  background: linear-gradient(to right, #2563eb 0%, #2563eb var(--fill, 0%), #e2e8f0 var(--fill, 0%), #e2e8f0 100%);
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #ffffff;
  border: 3px solid #2563eb;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.25);
}

.budget-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #ffffff;
  border: 3px solid #2563eb;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.25);
}

.budget-slider:focus-visible {
  box-shadow: 0 0 0 3px #dbeafe;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  font-size: 0.813rem;
  color: #64748b;
}

.place-order {
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.place-order:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.confirmation {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
  font-size: 0.938rem;
}

.confirmation-link {
  margin-left: auto;
  color: #2563eb;
  font-weight: 600;
  text-decoration: none;
}

.confirmation-link:hover {
  text-decoration: underline;
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: #64748b;
  font-size: 0.938rem;
}
</style>
