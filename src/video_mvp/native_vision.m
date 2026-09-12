#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <Vision/Vision.h>
#import <ImageIO/ImageIO.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

static void fail(NSString *message) {
    fprintf(stderr, "%s\n", message.UTF8String);
    exit(1);
}

static BOOL saveJPEG(CGImageRef image, NSURL *url, NSError **error) {
    CGImageDestinationRef destination = CGImageDestinationCreateWithURL(
        (__bridge CFURLRef)url,
        (__bridge CFStringRef)UTTypeJPEG.identifier,
        1,
        NULL
    );
    if (!destination) {
        if (error) {
            *error = [NSError errorWithDomain:@"AdsureVision" code:2 userInfo:@{
                NSLocalizedDescriptionKey: @"无法创建 JPEG 输出"
            }];
        }
        return NO;
    }
    CGImageDestinationAddImage(destination, image, (__bridge CFDictionaryRef)@{
        (__bridge NSString *)kCGImageDestinationLossyCompressionQuality: @0.88
    });
    BOOL ok = CGImageDestinationFinalize(destination);
    CFRelease(destination);
    return ok;
}

static NSArray *recognizeWithHandler(VNImageRequestHandler *handler) {
    VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
    request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    request.recognitionLanguages = @[@"zh-Hans", @"en-US"];
    request.usesLanguageCorrection = YES;
    request.minimumTextHeight = 0.005;
    NSError *error = nil;
    if (![handler performRequests:@[request] error:&error]) {
        NSString *detail = error
            ? [NSString stringWithFormat:@"%@ (%@:%ld)", error.localizedDescription, error.domain, (long)error.code]
            : @"OCR 失败（Vision 未返回错误对象）";
        return @[@{ @"error": detail }];
    }
    NSMutableArray *items = [NSMutableArray array];
    for (VNRecognizedTextObservation *observation in request.results) {
        VNRecognizedText *candidate = [[observation topCandidates:1] firstObject];
        if (!candidate || candidate.string.length == 0) continue;
        CGRect box = observation.boundingBox;
        [items addObject:@{
            @"text": candidate.string,
            @"confidence": @(candidate.confidence),
            // Vision is bottom-left based; web overlays are top-left based.
            @"bbox": @[@(box.origin.x), @(1.0 - box.origin.y - box.size.height), @(box.size.width), @(box.size.height)]
        }];
    }
    return items;
}

static NSArray *recognizeText(CGImageRef image) {
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:image options:@{}];
    return recognizeWithHandler(handler);
}

static NSArray *recognizeTextAtURL(NSURL *url) {
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithURL:url options:@{}];
    return recognizeWithHandler(handler);
}

static void emitJSON(id value) {
    NSError *jsonError = nil;
    NSData *json = [NSJSONSerialization dataWithJSONObject:value options:0 error:&jsonError];
    if (!json) fail(jsonError.localizedDescription);
    fwrite(json.bytes, 1, json.length, stdout);
    fputc('\n', stdout);
}

static void recognizeManifest(NSString *manifestPath) {
    NSData *data = [NSData dataWithContentsOfFile:manifestPath];
    if (!data) fail(@"无法读取 OCR 图像清单");
    NSError *parseError = nil;
    id parsed = [NSJSONSerialization JSONObjectWithData:data options:0 error:&parseError];
    if (![parsed isKindOfClass:[NSArray class]]) fail(parseError.localizedDescription ?: @"OCR 图像清单格式错误");
    NSMutableArray *frames = [NSMutableArray array];
    NSMutableArray *errors = [NSMutableArray array];
    for (NSDictionary *item in (NSArray *)parsed) {
        @autoreleasepool {
            NSString *path = item[@"imagePath"];
            if (![path isKindOfClass:[NSString class]]) continue;
            CGImageSourceRef source = CGImageSourceCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:path], NULL);
            CGImageRef image = source ? CGImageSourceCreateImageAtIndex(source, 0, NULL) : NULL;
            if (source) CFRelease(source);
            if (!image) {
                [errors addObject:@{ @"stage": @"load_frame", @"message": @"无法读取抽取画面", @"imagePath": path }];
                continue;
            }
            [frames addObject:@{
                @"frameId": item[@"frameId"] ?: @"frame",
                @"timestamp": item[@"timestamp"] ?: @0,
                @"imagePath": path,
                @"width": @(CGImageGetWidth(image)),
                @"height": @(CGImageGetHeight(image)),
                @"ocr": recognizeTextAtURL([NSURL fileURLWithPath:path])
            }];
            CGImageRelease(image);
        }
    }
    emitJSON(@{ @"frames": frames, @"errors": errors });
}

int main(int argc, const char * argv[]) {
    @autoreleasepool {
        if (argc == 3 && strcmp(argv[1], "--ocr-manifest") == 0) {
            recognizeManifest([NSString stringWithUTF8String:argv[2]]);
            return 0;
        }
        if (argc != 5) {
            fail(@"usage: adsure_vision <video> <output_dir> <interval_seconds> <max_frames>");
        }
        NSString *videoPath = [NSString stringWithUTF8String:argv[1]];
        NSString *outputPath = [NSString stringWithUTF8String:argv[2]];
        double interval = strtod(argv[3], NULL);
        NSInteger maxFrames = strtol(argv[4], NULL, 10);
        if (interval <= 0 || maxFrames <= 0) fail(@"interval and max_frames must be positive");

        NSFileManager *files = [NSFileManager defaultManager];
        NSError *directoryError = nil;
        if (![files createDirectoryAtPath:outputPath withIntermediateDirectories:YES attributes:nil error:&directoryError]) {
            fail(directoryError.localizedDescription);
        }
        NSURL *videoURL = [NSURL fileURLWithPath:videoPath];
        AVURLAsset *asset = [AVURLAsset URLAssetWithURL:videoURL options:nil];
        double duration = CMTimeGetSeconds(asset.duration);
        if (!isfinite(duration) || duration <= 0) fail(@"无法读取有效视频时长");

        AVAssetImageGenerator *generator = [[AVAssetImageGenerator alloc] initWithAsset:asset];
        generator.appliesPreferredTrackTransform = YES;
        generator.requestedTimeToleranceBefore = kCMTimeZero;
        generator.requestedTimeToleranceAfter = kCMTimeZero;

        NSMutableArray *frames = [NSMutableArray array];
        NSMutableArray *errors = [NSMutableArray array];
        NSInteger index = 0;
        for (double requested = 0.0; requested < duration && index < maxFrames; requested += interval, index++) {
            @autoreleasepool {
                CMTime requestedTime = CMTimeMakeWithSeconds(requested, 600);
                CMTime actualTime = kCMTimeInvalid;
                NSError *imageError = nil;
                CGImageRef image = [generator copyCGImageAtTime:requestedTime actualTime:&actualTime error:&imageError];
                if (!image) {
                    [errors addObject:@{
                        @"timestamp": @(requested),
                        @"stage": @"extract_frame",
                        @"message": imageError.localizedDescription ?: @"未知抽帧错误"
                    }];
                    continue;
                }
                double actual = CMTIME_IS_VALID(actualTime) ? CMTimeGetSeconds(actualTime) : requested;
                NSString *frameID = [NSString stringWithFormat:@"frame_%06ld", (long)index];
                NSString *fileName = [frameID stringByAppendingPathExtension:@"jpg"];
                NSString *imagePath = [outputPath stringByAppendingPathComponent:fileName];
                NSError *saveError = nil;
                if (!saveJPEG(image, [NSURL fileURLWithPath:imagePath], &saveError)) {
                    CGImageRelease(image);
                    [errors addObject:@{
                        @"timestamp": @(requested),
                        @"stage": @"save_frame",
                        @"message": saveError.localizedDescription ?: @"未知写图错误"
                    }];
                    continue;
                }
                NSArray *ocr = recognizeText(image);
                size_t width = CGImageGetWidth(image);
                size_t height = CGImageGetHeight(image);
                CGImageRelease(image);
                [frames addObject:@{
                    @"frameId": frameID,
                    @"timestamp": @(isfinite(actual) ? actual : requested),
                    @"imagePath": imagePath,
                    @"width": @(width),
                    @"height": @(height),
                    @"ocr": ocr
                }];
            }
        }

        NSDictionary *result = @{
            @"schemaVersion": @"adsure-native-vision/v1",
            @"duration": @(duration),
            @"sampleInterval": @(interval),
            @"maxFrames": @(maxFrames),
            @"frames": frames,
            @"errors": errors
        };
        emitJSON(result);
    }
    return 0;
}
