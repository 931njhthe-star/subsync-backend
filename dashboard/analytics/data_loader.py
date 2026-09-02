import pandas as pd


class DataLoader:
    @staticmethod
    def load_click_logs() -> pd.DataFrame:
        data = [
            {"word": "honest", "count": 48, "category": "형용사"},
            {"word": "living", "count": 35, "category": "동사"},
            {"word": "end up", "count": 29, "category": "숙어"},
            {"word": "procrastinate", "count": 22, "category": "동사"},
            {"word": "crucial", "count": 18, "category": "형용사"},
        ]
        return pd.DataFrame(data)


data_loader = DataLoader()
