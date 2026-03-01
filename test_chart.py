import sys
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QCategoryAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter

def test_chart():
    app = QApplication(sys.argv)
    window = QMainWindow()
    
    chart = QChart()
    series = QLineSeries()
    series.append(0, 1000)
    series.append(1, 500000)
    series.append(2, 1000000)
    chart.addSeries(series)
    
    axis_x = QCategoryAxis()
    axis_x.append("zero", 0)
    axis_x.append("one", 1)
    axis_x.append("two", 2)
    chart.addAxis(axis_x, Qt.AlignBottom)
    series.attachAxis(axis_x)
    
    axis_y = QCategoryAxis()
    axis_y.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
    axis_y.append("1K", 1000)
    axis_y.append("500K", 500000)
    axis_y.append("1M", 1000000)
    chart.addAxis(axis_y, Qt.AlignLeft)
    series.attachAxis(axis_y)
    
    view = QChartView(chart)
    view.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    window.setCentralWidget(view)
    window.resize(400, 300)
    
    # Render to a pixmap
    pixmap = view.grab()
    pixmap.save("test_chart.png")

if __name__ == "__main__":
    test_chart()
