import sys
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QDialog, 
                            QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                            QPushButton, QTimeEdit, QCheckBox, QSpinBox,
                            QTabWidget, QWidget, QMessageBox, QTextBrowser)
from PyQt5.QtGui import QIcon, QDesktopServices
from PyQt5.QtCore import Qt, QUrl, QTimer
from apscheduler.schedulers.qt import QtScheduler
from plyer import notification
from dateutil.parser import parse

# 常量定义
CONFIG_FILE = "config.json"
CACHE_FILE = "cache.json"
ICON_FILE = "icon.png"
NEWS_RSS = "http://rss.news.so.com/rss/2/guonei"

class ConfigManager:
    """配置管理类"""
    @staticmethod
    def load_config():
        default_config = {
            "work_time": {"start": "09:00", "end": "18:00"},
            "reminder": {
                "drink_interval": 120,
                "enable_news": True,
                "enable_huangli": True,
                "enable_holiday": True
            },
            "apis": {
                "holiday_source": "https://www.mxnzp.com/api/holiday/list/month/"
            }
        }
        config_path = Path(CONFIG_FILE)
        if not config_path.exists():
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=2)
        with open(config_path) as f:
            return json.load(f)

    @staticmethod
    def save_config(config):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)

class DataFetcher:
    """数据获取类（使用新API）"""
    @staticmethod
    def get_huangli():
        try:
            url = "https://www.mxnzp.com/api/holiday/single/"
            params = {
                "date": datetime.now().strftime("%Y%m%d"),
                "ignoreHoliday": False
            }
            res = requests.get(url, params=params, timeout=5)
            data = res.json()
            if data["code"] == 1:
                return {
                    "yi": "、".join(data["data"]["yi"]),
                    "ji": "、".join(data["data"]["ji"]),
                    "type": data["data"]["typeDesc"]
                }
            return None
        except Exception as e:
            print(f"获取黄历失败: {e}")
            return None

    @staticmethod
    def get_holidays(year, month):
        try:
            url = "https://www.mxnzp.com/api/holiday/list/month/"
            params = {
                "month": f"{year}-{month:02d}",
                "ignoreHoliday": False
            }
            res = requests.get(url, params=params, timeout=5)
            data = res.json()
            if data["code"] == 1:
                return {d["date"]: d for d in data["data"]}
            return {}
        except Exception as e:
            print(f"获取节假日失败: {e}")
            return {}

    @staticmethod
    def get_news():
        try:
            res = requests.get(NEWS_RSS, timeout=5)
            items = res.text.split("<item>")[1:6]
            news_list = []
            for item in items:
                title = item.split("<title>")[1].split("</title>")[0]
                link = item.split("<link>")[1].split("</link>")[0]
                news_list.append((title, link))
            return news_list
        except Exception as e:
            print(f"获取新闻失败: {e}")
            return []

class SettingsDialog(QDialog):
    """设置对话框（修复版）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFixedSize(400, 300)
        self.config = ConfigManager.load_config()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 工作时间设置
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("上班时间:"))
        self.start_time = QTimeEdit()
        self.start_time.setTime(parse(self.config['work_time']['start']).time())
        time_layout.addWidget(self.start_time)
        
        time_layout.addWidget(QLabel("下班时间:"))
        self.end_time = QTimeEdit()
        self.end_time.setTime(parse(self.config['work_time']['end']).time())
        time_layout.addWidget(self.end_time)
        layout.addLayout(time_layout)

        # 提醒间隔
        layout.addWidget(QLabel("喝水提醒间隔（分钟）:"))
        self.interval = QSpinBox()
        self.interval.setRange(30, 240)
        self.interval.setValue(self.config['reminder']['drink_interval'])
        layout.addWidget(self.interval)

        # 功能开关
        self.news_check = QCheckBox("启用新闻提醒")
        self.news_check.setChecked(self.config['reminder']['enable_news'])
        layout.addWidget(self.news_check)

        self.huangli_check = QCheckBox("启用黄历功能")
        self.huangli_check.setChecked(self.config['reminder']['enable_huangli'])
        layout.addWidget(self.huangli_check)

        # 按钮
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_settings)
        btn_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def save_settings(self):
        self.config['work_time']['start'] = self.start_time.time().toString("HH:mm")
        self.config['work_time']['end'] = self.end_time.time().toString("HH:mm")
        self.config['reminder']['drink_interval'] = self.interval.value()
        self.config['reminder']['enable_news'] = self.news_check.isChecked()
        self.config['reminder']['enable_huangli'] = self.huangli_check.isChecked()
        ConfigManager.save_config(self.config)
        self.accept()

class AssistantApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        
        # 初始化组件
        self.config = ConfigManager.load_config()
        self.tray_icon = self.init_tray()
        self.scheduler = QtScheduler()
        self.cache = self.load_cache()
        
        # 设置定时任务
        self.setup_scheduler()
        self.scheduler.start()
        
        # 立即同步数据
        QTimer.singleShot(1000, self.sync_data)
        
        sys.exit(self.app.exec_())

    def init_tray(self):
        """初始化系统托盘"""
        if not Path(ICON_FILE).exists():
            QMessageBox.critical(None, "错误", f"图标文件 {ICON_FILE} 不存在！")
            sys.exit(1)
            
        tray = QSystemTrayIcon(QIcon(ICON_FILE), self.app)
        tray.setToolTip("桌面助手")
        
        menu = QMenu()
        menu.addAction("今日黄历", self.show_huangli)
        menu.addAction("近期假期", self.show_holidays)
        menu.addAction("最新新闻", self.show_news)
        menu.addSeparator()
        menu.addAction("设置", self.show_settings)
        menu.addAction("同步数据", self.sync_data)
        menu.addAction("退出", self.app.quit)
        tray.setContextMenu(menu)
        tray.show()
        return tray

    def setup_scheduler(self):
        """设置定时任务"""
        # 上下班提醒
        work_start = parse(self.config['work_time']['start']).time()
        work_end = parse(self.config['work_time']['end']).time()
        self.scheduler.add_job(self.work_reminder, 'cron', 
                             hour=work_start.hour, minute=work_start.minute)
        self.scheduler.add_job(self.work_reminder, 'cron', 
                             hour=work_end.hour, minute=work_end.minute)
        
        # 喝水提醒
        self.scheduler.add_job(self.drink_reminder, 'interval', 
                             minutes=self.config['reminder']['drink_interval'])
        
        # 每日数据同步
        self.scheduler.add_job(self.sync_data, 'cron', hour=8)
        
        # 新闻提醒
        if self.config['reminder']['enable_news']:
            self.scheduler.add_job(self.news_reminder, 'cron', hour=9)

    def sync_data(self):
        """同步所有数据"""
        try:
            now = datetime.now()
            
            # 黄历数据
            if self.config['reminder']['enable_huangli']:
                self.cache['huangli'] = DataFetcher.get_huangli()
            
            # 节假日数据（获取未来3个月）
            self.cache['holidays'] = {}
            for m_offset in [0, 1, 2]:
                month = (now.month + m_offset - 1) % 12 + 1
                year = now.year + (now.month + m_offset - 1) // 12
                self.cache['holidays'].update(
                    DataFetcher.get_holidays(year, month)
                )
            
            # 新闻数据
            if self.config['reminder']['enable_news']:
                self.cache['news'] = DataFetcher.get_news()
            
            self.save_cache()
            self.show_notification("数据更新", "数据同步完成")
        except Exception as e:
            print(f"数据同步失败: {e}")

    def show_holidays(self):
        """显示假期信息"""
        holidays = self.cache.get('holidays', {})
        content = []
        today = datetime.now().strftime("%Y-%m-%d")
        for date_str in sorted(holidays.keys()):
            if date_str >= today:
                info = holidays[date_str]
                content.append(
                    f"{info['date']} {info['typeDes']} "
                    f"({'休息' if info['isOffDay'] else '工作日'})"
                )
                if len(content) >= 5:
                    break
        self.show_detail_window("近期假期", "\n".join(content))

    # 其他方法保持不变（work_reminder、drink_reminder等）

if __name__ == "__main__":
    AssistantApp()