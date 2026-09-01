# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd
import numpy as np
import lightgbm as lgb
from dateutil.relativedelta import relativedelta
from typing import Optional


class ModelStore:
    """LightGBM 模型路径、缓存、训练截止月与读写（规避 Windows 非 ASCII 路径）。

    文件名：{品类}_{系列}_{训练截止月}-N{1~7}.txt
    例：冰箱_L_2026-07-N1.txt … 冰箱_L_2026-07-N7.txt
    """

    def __init__(self, model_dir: str):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict = {}
        self.train_count = 0
        self.load_count = 0

    @staticmethod
    def train_time(base_target_month) -> str:
        """训练数据最新月份：base_target_month（N+1）的上一个月，格式 YYYY-MM。"""
        return (pd.to_datetime(base_target_month) - relativedelta(months=1)).strftime('%Y-%m')

    @staticmethod
    def horizon_tag(horizon_offset: int) -> str:
        """horizon_offset 0→N1 … 6→N7。"""
        return f'N{int(horizon_offset) + 1}'

    def stem(self, category: str, series: str, train_time: str, horizon_offset: int = 0) -> str:
        return f'{category}_{series}_{train_time}-{self.horizon_tag(horizon_offset)}'

    def model_path(self, category: str, series: str, train_time: str, horizon_offset: int = 0) -> Path:
        return self.model_dir / f'{self.stem(category, series, train_time, horizon_offset)}.txt'

    def bias_path(self, category: str, series: str, train_time: str, horizon_offset: int = 0) -> Path:
        return self.model_dir / f'{self.stem(category, series, train_time, horizon_offset)}.bias.csv'

    def get_cached(self, cache_key):
        if cache_key in self._cache:
            self.load_count += 1
            return self._cache[cache_key]
        return None

    def put_cache(self, cache_key, gbm) -> None:
        self._cache[cache_key] = gbm

    def save(self, gbm: lgb.Booster, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(gbm.model_to_string(), encoding='utf-8')

    def load(self, path: Path) -> lgb.Booster:
        return lgb.Booster(model_str=path.read_text(encoding='utf-8'))

    def train(self, X_train, y_train, model_params, categorical_features):
        try:
            dataset = lgb.Dataset(X_train, y_train, categorical_feature=categorical_features)
            return lgb.train(model_params, dataset)
        except Exception as e:
            print("模型训练失败:", str(e))
            return None

    def load_or_train(self, cache_key, category, series, train_time, horizon_offset,
                      X_train, y_train, model_params, categorical_features):
        """内存命中 / 磁盘加载 / 训练落盘，返回 gbm 或 None。按 horizon 分模型。"""
        stem = self.stem(category, series, train_time, horizon_offset)
        cached = self.get_cached(cache_key)
        if cached is not None:
            print(f">>>> LGBM memory hit: {stem}")
            return cached

        path = self.model_path(category, series, train_time, horizon_offset)
        if path.exists():
            gbm = self.load(path)
            self.put_cache(cache_key, gbm)
            self.load_count += 1
            print(f">>>> LGBM loaded: {path}")
            return gbm

        gbm = self.train(X_train, y_train, model_params, categorical_features)
        if gbm is None:
            return None

        self.save(gbm, path)
        self.put_cache(cache_key, gbm)
        self.train_count += 1
        print(f">>>> LGBM trained & saved: {path}")
        return gbm


class BiasStore:
    """训练期预测偏差的计算、缓存与 sidecar 读写。"""

    def __init__(self):
        self._cache: dict = {}

    def get_cached(self, cache_key):
        return self._cache.get(cache_key)

    def put_cache(self, cache_key, bias_df) -> None:
        if bias_df is not None and not bias_df.empty:
            self._cache[cache_key] = bias_df

    @staticmethod
    def compute(train_df: pd.DataFrame) -> pd.DataFrame:
        """按渠道+型号聚合训练期偏差（需含 model_pred、数量）。"""
        bias = train_df.copy()
        bias['pred_bias'] = bias['model_pred'] - bias['数量']
        return (
            bias.groupby(['3级渠道', '型号-CRM最新名称'], as_index=False)['pred_bias']
            .mean()
        )

    @staticmethod
    def save(path: Path, bias_df: pd.DataFrame) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        bias_df.to_csv(path, index=False, encoding='utf-8-sig')

    @staticmethod
    def load(path: Path):
        if not path.exists():
            return None
        return pd.read_csv(path, encoding='utf-8-sig')

    def resolve(self, cache_key, path: Path, train_df_with_pred: pd.DataFrame):
        """优先缓存/磁盘；缺失则用训练集补算并落盘。"""
        bias_df = self.get_cached(cache_key)
        if bias_df is not None and not bias_df.empty:
            return bias_df

        bias_df = self.load(path)
        if bias_df is None or bias_df.empty:
            bias_df = self.compute(train_df_with_pred)
            self.save(path, bias_df)

        self.put_cache(cache_key, bias_df)
        return bias_df


class MLPredictor:
    """机器学习预测器（LightGBM）：编排特征拆分，委托 ModelStore / BiasStore。"""

    def __init__(self, config):
        self.config = config
        self.gbm = None
        self.models = ModelStore(config.MODEL_FILE_DIR)
        self.bias = BiasStore()
        self.last_feature_names: list = []
        self.last_categorical_features: list = []
        self._last_prepared_df: Optional[pd.DataFrame] = None

    @property
    def train_count(self):
        return self.models.train_count

    @property
    def load_count(self):
        return self.models.load_count

    def predict(
        self,
        df,
        target_month,
        series_type,
        base_target_month,
        category,
        series,
        horizon_offset: int = 0,
    ):
        """执行完整预测流程：同品类×系列×训练截止月×horizon(N1~N7) 复用模型。"""
        try:
            cutoff_date = pd.to_datetime(target_month)
            prepared_df = df[df['月份'] <= cutoff_date].copy()
            if prepared_df.empty:
                return pd.DataFrame(), pd.DataFrame(), None

            series_config = self.config.SERIES_CONFIG.get(series_type, {})
            model_features = series_config.get('MODEL_FEATURES', '')
            categorical_features = series_config.get('CATEGORICAL_FEATURES', '')
            model_params = self.config.MODEL_PARAMS
            self.last_feature_names = sorted(model_features)
            self.last_categorical_features = list(categorical_features)

            self._handle_categorical(prepared_df, categorical_features)
            self._last_prepared_df = prepared_df
            split_data = self._split_data(prepared_df, target_month, model_features, base_target_month)
            if not split_data:
                return pd.DataFrame(), pd.DataFrame(), None
            X_train, y_train, X_test, train_df, test_df = split_data

            train_time = self.models.train_time(base_target_month)
            horizon_offset = int(horizon_offset)
            cache_key = (category, series, train_time, horizon_offset)
            self.gbm = self.models.load_or_train(
                cache_key, category, series, train_time, horizon_offset,
                X_train, y_train, model_params, categorical_features,
            )
            if self.gbm is None:
                return pd.DataFrame(), pd.DataFrame(), None

            train_df = train_df.copy()
            test_df = test_df.copy()
            train_df['model_pred'] = np.round(self.gbm.predict(X_train), 0)
            test_df['model_pred'] = np.round(self.gbm.predict(X_test), 0)

            bias_df = self.bias.resolve(
                cache_key,
                self.models.bias_path(category, series, train_time, horizon_offset),
                train_df,
            )
            return train_df, test_df, bias_df
        except Exception as e:
            print("预测流程异常:", str(e))
            return pd.DataFrame(), pd.DataFrame(), None

    def prepare_feature_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        """按上次预测的特征配置处理分类列，供 SHAP 使用。"""
        out = df.copy()
        if self.last_categorical_features:
            self._handle_categorical(out, self.last_categorical_features)
        return out

    def shap_relative_to_prior_month(self, feature_df: pd.DataFrame, target_month) -> pd.DataFrame:
        """
        对目标月样本相对「上月」同键特征做 TreeSHAP 差分。
        优先复用 predict() 刚编码的 _last_prepared_df，保证类别特征码与训练一致。
        """
        from attribution import ShapExplainer

        if self.gbm is None:
            return pd.DataFrame()

        # 特征序与 Booster 对齐
        try:
            feature_names = list(self.gbm.feature_name())
        except Exception:
            feature_names = list(self.last_feature_names)
        if not feature_names:
            return pd.DataFrame()

        target_dt = pd.to_datetime(target_month).to_period('M').to_timestamp()
        prior_dt = target_dt - relativedelta(months=1)

        if self._last_prepared_df is not None and not self._last_prepared_df.empty:
            prepared = self._last_prepared_df.copy()
        else:
            prepared = self.prepare_feature_frame(feature_df)

        missing = [c for c in feature_names if c not in prepared.columns]
        if missing:
            print(f"SHAP 缺少特征列，跳过: {missing[:5]}...")
            return pd.DataFrame()

        prepared = prepared.copy()
        prepared['月份'] = pd.to_datetime(prepared['月份']).dt.to_period('M').dt.to_timestamp()
        curr = prepared[prepared['月份'] == target_dt].copy().reset_index(drop=True)
        prior = prepared[prepared['月份'] == prior_dt].copy().reset_index(drop=True)
        if curr.empty:
            return pd.DataFrame()

        meta = [c for c in ['品类', 'series', '1级渠道', 'status'] if c in curr.columns]
        return ShapExplainer.relative_to_prior_month(
            self.gbm, curr, prior, feature_names, meta_cols=meta,
        )

    def _handle_categorical(self, df, categorical_features):
        for col in categorical_features:
            if col not in df.columns:
                raise ValueError(f"分类特征 {col} 缺失")
            df[col] = df[col].astype('category')

    def _split_data(self, df, target_month, model_features, base_target_month):
        try:
            test_date = pd.to_datetime(target_month)
            base_date = pd.to_datetime(base_target_month)
            train_mask = df['月份'] < base_date
            test_mask = df['月份'] == test_date
            ordered_features = sorted(model_features)
            return (
                df[train_mask][ordered_features],
                df[train_mask]['数量'],
                df[test_mask][ordered_features],
                df[train_mask],
                df[test_mask],
            )
        except KeyError as e:
            print("数据拆分错误 - 缺失列:", str(e))
            return None


class MAPredictor:
    def __init__(self, config):
        self.config = config

    def predict(self, unpredictable_skus, final_data, target_month, series, skytype):
        """生成 MA 预测结果。"""
        results = []
        for (channel, skuname), avg in unpredictable_skus:
            df = final_data[(final_data['3级渠道'] == channel) & (final_data['型号-CRM最新名称'] == skuname)]
            set_data = df[(df['series'] == series) & (df['品类'] == skytype)]
            if not set_data.empty:
                current_month_data = set_data[set_data['月份'] == pd.to_datetime(target_month)]
                current_price = current_month_data['avg_price'].iloc[0] if not current_month_data.empty else 0
                results.append({
                    '月份': pd.to_datetime(target_month),
                    'product_line_code': set_data['product_line_code'].iloc[-1],
                    'product_line_name': set_data['product_line_name'].iloc[-1],
                    '品类': skytype,
                    '1级渠道': set_data['1级渠道'].iloc[-1],
                    '3级渠道': channel,
                    'series': series,
                    'status': set_data['status'].iloc[-1],
                    '型号-CRM最新名称': skuname,
                    '数量': 0,
                    'method': 'MA',
                    'avg_price': current_price,
                    'qty_lag1': set_data['qty_lag1'].iloc[-1],
                    'lag1_diff1': set_data['lag1_diff1'].iloc[-1],
                    'qty_lag12': set_data['qty_lag12'].iloc[-1],
                    'qty_lag1_3m_mean': set_data['qty_lag1_3m_mean'].iloc[-1],
                    'y_pred': np.nan_to_num(avg),
                })
        return pd.DataFrame(results)
