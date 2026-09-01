import requests
import json
import sys
import time
from datetime import datetime


class PredictionClient:
    def __init__(self, base_url="http://localhost:8000"):
        # 初始化客户端，设置API服务地址
        self.base_url = base_url
        self.predict_url = f"{base_url}/predict"
        self.tasks_url = f"{base_url}/tasks"
    
    def check_server_health(self):
        """检查服务是否可用"""
        try:
            response = requests.get(f"{self.base_url}/health")
            if response.status_code == 200:
                health_data = response.json()
                print(f"服务状态: {health_data.get('status')}")
                print(f"活跃任务: {health_data.get('active_tasks')}")
                print(f"总任务数: {health_data.get('total_tasks')}")
                return True
            return False
        except requests.exceptions.ConnectionError:
            return False
    
    def run_prediction(self, systemForecastNumber, productLine, reporter, generateTime, 
                      attributeBatchNumber, priceBatchNumber, callbackUrl=None):
        """提交异步预测任务"""
        payload = {
            "systemForecastNumber": systemForecastNumber,
            "productLine": productLine,
            "reporter": reporter,
            "generateTime": generateTime,
            "attributeBatchNumber": attributeBatchNumber,
            "priceBatchNumber": priceBatchNumber,
        }
        
        # 添加可选的回调URL
        if callbackUrl:
            payload["customCallbackUrl"] = callbackUrl
        
        print(f"提交预测任务: {json.dumps(payload, indent=2, ensure_ascii=False)}")
        
        try:
            # 发送POST请求到预测接口
            response = requests.post(
                self.predict_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30  # 提交请求超时时间较短
            )
            
            if response.status_code == 200:
                result = response.json()
                print("预测任务提交成功")
                return result
            else:
                error_msg = f"请求失败: {response.status_code} - {response.text}"
                print(error_msg)
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            error_msg = f"发生错误: {str(e)}"
            print(error_msg)
            return {"success": False, "error": error_msg}
    
    def get_task_status(self, task_id):
        """查询任务状态"""
        try:
            response = requests.get(f"{self.tasks_url}/{task_id}")
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"获取任务状态失败: {response.status_code} - {response.text}"}
        except Exception as e:
            return {"error": f"查询任务状态时发生错误: {str(e)}"}
    
    def list_tasks(self, status=None, limit=10):
        """列出任务"""
        params = {"limit": limit}
        if status:
            params["status"] = status
            
        try:
            response = requests.get(self.tasks_url, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"获取任务列表失败: {response.status_code}"}
        except Exception as e:
            return {"error": f"获取任务列表时发生错误: {str(e)}"}
    
    def wait_for_completion(self, task_id, poll_interval=5, timeout=3600):
        """等待任务完成"""
        start_time = time.time()
        print(f"开始等待任务完成 - 任务ID: {task_id}")
        
        while time.time() - start_time < timeout:
            status_result = self.get_task_status(task_id)
            
            if "error" in status_result:
                print(f"查询任务状态失败: {status_result['error']}")
                return status_result
            
            status = status_result.get("status")
            progress = status_result.get("progress", "")
            
            print(f"任务状态: {status} - {progress}")
            
            if status == "completed":
                print("任务执行完成!")
                return status_result
            elif status == "failed":
                print(f"任务执行失败: {status_result.get('error_message', '未知错误')}")
                return status_result
            elif status in ["pending", "running"]:
                # 任务还在进行中，继续等待
                time.sleep(poll_interval)
            else:
                print(f"未知的任务状态: {status}")
                return status_result
        
        print(f"等待超时 ({timeout} 秒)")
        return {"error": "等待任务完成超时"}
    
    def retry_callback(self, task_id):
        """重新发送回调通知"""
        try:
            response = requests.post(f"{self.tasks_url}/{task_id}/retry-callback")
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"重新发送回调失败: {response.status_code} - {response.text}"}
        except Exception as e:
            return {"error": f"重新发送回调时发生错误: {str(e)}"}
    
    def print_task_result(self, task_result):
        """格式化打印任务结果"""
        print("\n" + "="*50)
        print("任务执行结果")
        print("="*50)
        
        if "error" in task_result:
            print(f"错误: {task_result['error']}")
            return
        
        task_id = task_result.get('task_id')
        status = task_result.get('status')
        progress = task_result.get('progress', '')
        
        print(f"任务ID: {task_id}")
        print(f"状态: {status}")
        print(f"进度: {progress}")
        print(f"创建时间: {task_result.get('created_time')}")
        
        if task_result.get('completed_time'):
            print(f"完成时间: {task_result.get('completed_time')}")
        
        if status == "completed":
            result_data = task_result.get('result')
            if result_data:
                print(f"\n预测结果数据:")
                print(f"  系统预测编号: {result_data.get('systemForecastNumber')}")
                print(f"  产线编码: {result_data.get('productLine')}")
                print(f"  填报人: {result_data.get('reporter')}")
                print(f"  生成时间: {result_data.get('generateTime')}")
                print(f"  属性批次号: {result_data.get('attributeBatchNumber')}")
                print(f"  价格批次号: {result_data.get('priceBatchNumber')}")
                
                # 如果有详细数据，可以打印出来
                data = result_data.get('data')
                if data:
                    print(f"  详细数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        elif status == "failed":
            error_msg = task_result.get('error_message', '未知错误')
            print(f"错误信息: {error_msg}")
        
        print("="*50)
    
    def print_submission_result(self, submission_result):
        """格式化打印任务提交结果"""
        print("\n" + "="*50)
        print("任务提交结果")
        print("="*50)
        
        if submission_result.get('success') is False:
            print(f"提交失败: {submission_result.get('error')}")
            return
        
        task_id = submission_result.get('task_id')
        status = submission_result.get('status')
        message = submission_result.get('message')
        systemForecastNumber = submission_result.get('systemForecastNumber')
        productLine = submission_result.get('productLine')
        callback_url = submission_result.get('callback_url')
        
        print(f"任务ID: {task_id}")
        print(f"状态: {status}")
        print(f"消息: {message}")
        print(f"系统预测编号: {systemForecastNumber}")
        print(f"产线编码: {productLine}")
        if callback_url:
            print(f"回调URL: {callback_url}")
        
        print("="*50)


def print_params(systemForecastNumber, productLine, reporter, generateTime, 
                attributeBatchNumber, priceBatchNumber, server_url, callback_url=None):
    """打印使用的参数"""
    print('=' * 80)
    print("使用的参数:")
    print(f"  系统预测编号: {systemForecastNumber}")
    print(f"  产线编码: {productLine}")
    print(f"  填报人: {reporter}")
    print(f"  生成时间: {generateTime}")
    print(f"  属性批次号: {attributeBatchNumber}")
    print(f"  价格批次号: {priceBatchNumber}")
    print(f"  服务器地址: {server_url}")
    if callback_url:
        print(f"  回调地址: {callback_url}")
    print('=' * 80)


def main():
    # 预设参数 - 在此处直接设置参数值
    systemForecastNumber = "YC_001_CB"
    productLine = "PL003"
    reporter = "CB-test-1"
    generateTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    attributeBatchNumber = "SX_PL003"
    priceBatchNumber = "JG_PL003"
    server_url = "http://localhost:8000"
    callback_url = "http://localhost:8001/v1/18/forecast-result-infos/completed/YC_001_CB"  # 可选
    
    # 是否等待任务完成
    wait_for_completion = True  # 设置为False则只提交不等待
    
    print_params(systemForecastNumber, productLine, reporter, generateTime, 
                attributeBatchNumber, priceBatchNumber, server_url, callback_url)
    
    # 创建客户端并检查服务状态
    client = PredictionClient(base_url=server_url)
    
    if not client.check_server_health():
        print("服务不可用，请先启动预测服务器")
        sys.exit(1)
    
    # 提交预测任务
    submission_result = client.run_prediction(
        systemForecastNumber=systemForecastNumber,
        productLine=productLine,
        reporter=reporter,
        generateTime=generateTime,
        attributeBatchNumber=attributeBatchNumber,
        priceBatchNumber=priceBatchNumber,
        callbackUrl=callback_url
    )
    
    client.print_submission_result(submission_result)
    
    # 检查提交是否成功
    if submission_result.get('success') is False:
        print("任务提交失败")
        sys.exit(1)
    
    task_id = submission_result.get('task_id')
    
    if wait_for_completion:
        # 等待任务完成
        print(f"\n开始等待任务完成，任务ID: {task_id}")
        final_result = client.wait_for_completion(task_id)
        client.print_task_result(final_result)
        
        # 根据结果返回退出码
        if final_result.get('status') == 'completed':
            sys.exit(0)
        else:
            sys.exit(1)
    else:
        print(f"\n任务已提交，任务ID: {task_id}")
        print("使用以下命令查看任务状态:")
        print(f"  curl {server_url}/tasks/{task_id}")
        sys.exit(0)


if __name__ == "__main__":
    main()