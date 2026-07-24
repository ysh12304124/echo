import cv2


def filter_face_quality(
        img,
        face,
        blur_threshold=50
):
    """
    判断人脸是否适合进行表情分析
    face:
    (x,y,w,h,is_real,antispoof_score)
    """
    x, y, w, h = face[:4]
    H, W = img.shape[:2]
    # =====================
    # 1. 判断是否完整
    # =====================
    margin = 5
    if x <= margin:
        return False
    if y <= margin:
        return False
    if x + w >= W - margin:
        return False
    if y + h >= H - margin:
        return False
    # =====================
    # 2. 清晰度检测
    # =====================
    face_img = img[
        y:y+h,
        x:x+w
    ]
    if face_img.size == 0:
        return False
    gray = cv2.cvtColor(
        face_img,
        cv2.COLOR_BGR2GRAY
    )
    blur_score = cv2.Laplacian(
        gray,
        cv2.CV_64F
    ).var()
    if blur_score < blur_threshold:
        return False
    return True