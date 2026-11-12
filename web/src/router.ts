import { createRouter, createWebHistory } from 'vue-router'
import OverviewView from './views/OverviewView.vue'
import MapView from './views/MapView.vue'
import AnalysisView from './views/AnalysisView.vue'
import ResultsView from './views/ResultsView.vue'
import ComparisonView from './views/ComparisonView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: OverviewView, meta: { title: '项目总览', section: '工作台' } },
    { path: '/comparison', name: 'comparison', component: ComparisonView, meta: { title: '方法对比', section: '工作台' } },
    { path: '/map', name: 'map', component: MapView, meta: { title: '时空地图', section: '空间分析' } },
    { path: '/expansion', name: 'expansion', component: AnalysisView, meta: { title: '街镇扩张', section: '空间分析', resource: 'expansion' } },
    { path: '/accuracy', name: 'accuracy', component: AnalysisView, meta: { title: '分类精度', section: '模型评价', resource: 'accuracy' } },
    { path: '/transitions', name: 'transitions', component: AnalysisView, meta: { title: '地类转移', section: '模型评价', resource: 'transitions' } },
    { path: '/drivers', name: 'drivers', component: AnalysisView, meta: { title: '驱动因素', section: '专题分析', resource: 'drivers' } },
    { path: '/terrain', name: 'terrain', component: AnalysisView, meta: { title: '地形与洪涝', section: '专题分析', resource: 'terrain' } },
    { path: '/landscape', name: 'landscape', component: AnalysisView, meta: { title: '耕地与景观', section: '专题分析', resource: 'landscape' } },
    { path: '/policies', name: 'policies', component: AnalysisView, meta: { title: '政策叠加', section: '专题分析', resource: 'policies' } },
    { path: '/results', name: 'results', component: ResultsView, meta: { title: '成果中心', section: '项目成果' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
